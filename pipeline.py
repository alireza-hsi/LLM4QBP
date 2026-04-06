#!/usr/bin/env python3
"""
Unified pipeline for MAO (AiO version) and ProMoAI frameworks,
including activity mapping, BPMN comparison, and logging results.

Supports:
- Batch mode via --batch-manifest (JSON from Streamlit UI)
- Parallel execution via --max-workers
- Incremental DB writes (crash-safe; writes as each run completes)
- Progress output lines for Streamlit parsing: "PROGRESS X/Y"

Batch manifest item format (from the Streamlit UI):
[
  {
    "id": "a1b2c3d4",
    "framework": "ProMoAI" | "MAO (AiO version)",
    "runs": 5,
    "name": "PipelineRun",
    "model": "GPT_5o2",
    "mapping_model": "gpt-5.2",
    "config": "Version-3.8",     # MAO only
    "org": "Version-3.8",        # MAO only
    "task_file": "/tmp/.../id__QBP1.txt",
    "gold_bpmn": "/tmp/.../id__QBP1.bpmn" | null,
    "gold_bpmn_filename": "QBP1.bpmn" | null
  }
]
"""
import argparse
import os
import sys
import subprocess
import sqlite3
import re
import json
import shutil
import uuid
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from queue import Queue
from threading import Thread

# Conda env names can be set by Streamlit via env vars; defaults provided.
PROMOAI_ENV = os.environ.get("PROMOAI_ENV", "promoai")
MAO_ENV = os.environ.get("MAO_ENV", "mao")

# Ensure your MAO helpers are on PYTHONPATH
MAO_HELPER = os.path.join("MAO", "MAO(AiO version)", "Code", "Helper")
sys.path.insert(0, MAO_HELPER)

from automatedActivityMapping import (
    extract_activity_names,
    get_alignment,
    get_revision,
    update_activity_names,
)
from bpmn_compare_similarity import CompareBPMN
from duplicateHandling import remove_safe_duplicates


# ---------------------------
# Args
# ---------------------------
def parse_args():
    p = argparse.ArgumentParser()

    # Batch mode
    p.add_argument("--batch-manifest", default=None,
                   help="JSON list of experiments (from Streamlit UI).")
    p.add_argument("--max-workers", type=int, default=1,
                   help="Parallel workers for batch jobs.")
    p.add_argument("--batch-id", default=None,
                   help="Optional batch id for grouping; if omitted a UUID is generated.")

    # Single mode (backwards compatible)
    p.add_argument("--framework", choices=["ProMoAI", "MAO (AiO version)"], required=False)
    p.add_argument("--task-file", required=False)
    p.add_argument("--gold-bpmn", required=False)
    p.add_argument("--runs", type=int, default=1)
    p.add_argument("--config", default=None)
    p.add_argument("--org", default=None)
    p.add_argument("--name", default="PipelineProject")
    p.add_argument("--model", default="GPT_5o2")
    p.add_argument("--mapped-output", default=None)
    p.add_argument("--results-db", default="resultsDb.sqlite")
    p.add_argument("--gold-bpmn-filename", default=None)
    p.add_argument("--mapping-model", default="gpt-5.2")
    p.add_argument(
        "--use-dedup",
        action="store_true",
        help="Run duplicate handling on the final BPMN artefact before similarity comparison.",
    )

    return p.parse_args()


# ---------------------------
# DB helpers (WAL + create tables)
# ---------------------------
def db_connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=30)
    # Improve robustness under frequent writes
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA busy_timeout=30000;")
    return conn


def db_init(conn: sqlite3.Connection):
    c = conn.cursor()

    # Your existing table (kept as-is)
    c.execute("""
      CREATE TABLE IF NOT EXISTS experiment_results (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT,
        qbp_name TEXT,
        framework TEXT,
        node_similarity REAL,
        structure_similarity REAL,
        graph_edit_distance INTEGER,
        gold_bpmn_path TEXT,
        generated_bpmn_path TEXT,
        model TEXT,
        promoai_retries TEXT
      )
    """)

    # Add optional columns for additional artefact paths if they don't exist yet.
    try:
        c.execute("ALTER TABLE experiment_results ADD COLUMN mapped_bpmn_path TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        c.execute("ALTER TABLE experiment_results ADD COLUMN dedup_bpmn_path TEXT")
    except sqlite3.OperationalError:
        pass

    # New run-level tracking (for progress/resume/debug)
    c.execute("""
      CREATE TABLE IF NOT EXISTS experiment_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        batch_id TEXT,
        job_id TEXT,
        qbp_name TEXT,
        framework TEXT,
        run_index INTEGER,
        status TEXT,
        started_at TEXT,
        finished_at TEXT,
        error TEXT,
        UNIQUE(batch_id, job_id)
      )
    """)

    conn.commit()


def db_mark_started(conn: sqlite3.Connection, batch_id: str, job_id: str,
                    qbp: str, framework: str, run_index: int):
    conn.execute("""
      INSERT OR IGNORE INTO experiment_runs
        (batch_id, job_id, qbp_name, framework, run_index, status, started_at, finished_at, error)
      VALUES
        (?, ?, ?, ?, ?, 'started', datetime('now'), NULL, NULL)
    """, (batch_id, job_id, qbp, framework, run_index))
    conn.commit()


def db_mark_finished(conn: sqlite3.Connection, batch_id: str, job_id: str,
                     status: str, error: str | None):
    conn.execute("""
      UPDATE experiment_runs
      SET status=?, finished_at=datetime('now'), error=?
      WHERE batch_id=? AND job_id=?
    """, (status, error, batch_id, job_id))
    conn.commit()


def db_insert_result(conn: sqlite3.Connection, qbp: str, framework: str,
                     node_sim, struct_sim, ged,
                     gold, gen, mapped, dedup, model, promoai_retries):
    conn.execute("""
      INSERT INTO experiment_results (
        timestamp, qbp_name, framework,
        node_similarity, structure_similarity, graph_edit_distance,
        gold_bpmn_path, generated_bpmn_path, mapped_bpmn_path, dedup_bpmn_path,
        model, promoai_retries
      ) VALUES (datetime('now'),?,?,?,?,?,?,?,?,?,?,?)
    """, (qbp, framework, node_sim, struct_sim, ged, gold, gen, mapped, dedup, model, promoai_retries))
    conn.commit()


# ---------------------------
# Misc helpers
# ---------------------------
def _stem(path: str) -> str:
    return os.path.splitext(os.path.basename(path))[0]


def _safe_makedirs(path: str):
    if path and not os.path.exists(path):
        os.makedirs(path, exist_ok=True)


def _conda_prefix(env_name: str):
    conda_exe = shutil.which("conda")
    if conda_exe:
        return [conda_exe, "run", "-n", env_name, "python", "-u"]
    return None


def _strip_eid_prefix(filename: str, eid: str) -> str:
    base = os.path.basename(filename)
    prefix = f"{eid}__"
    if base.startswith(prefix):
        base = base[len(prefix):]
    return os.path.splitext(base)[0]


# ---------------------------
# Framework runners
# ---------------------------
def run_mao(task_file, config, org, name, model, code_root):
    script = os.path.join(code_root, "run.py")

    # Prefer MAO conda env if available; otherwise fallback
    prefix = _conda_prefix(MAO_ENV)
    if prefix is None:
        prefix = [sys.executable, "-u"]

    cmd = prefix + [
        script,
        "--task-file", task_file,
        "--config", config,
        "--org", org,
        "--name", name
    ]
    if model:
        cmd += ["--model", model]

    result = subprocess.run(cmd, check=True, capture_output=True, text=True)
    bpmn_path = result.stdout.strip().splitlines()[-1]
    return bpmn_path


def run_promoai(task_file, model, code_root, project_name):
    script = "ProMoAI_API.py"
    prefix = _conda_prefix(PROMOAI_ENV)
    if prefix is None:
        raise RuntimeError("conda not found on PATH, but ProMoAI execution requires conda env.")

    cmd = prefix + [
        script,
        "--task-file", task_file,
        "--model", model,
        "--output-dir", "WareHouse",
        "--project-name", project_name
    ]

    result = subprocess.run(cmd, cwd=code_root, check=True, capture_output=True, text=True)

    lines = result.stdout.strip().splitlines()
    promoai_retries = None
    bpmn_path = None
    for line in lines:
        if line.startswith("PROMOAI_RETRIES:"):
            promoai_retries = line.split("PROMOAI_RETRIES:", 1)[1].strip()
        elif line.endswith(".bpmn"):
            bpmn_path = line
    return bpmn_path, promoai_retries


# ---------------------------
# Mapping + Compare
# ---------------------------
def extract_python_lists(text):
    import ast
    set_a = set_c = None
    for var in ("Set_A", "Set_C"):
        m = re.search(rf"{var}\s*=\s*(\[[\s\S]*?\])", text)
        if m:
            try:
                val = ast.literal_eval(m.group(1))
                if var == "Set_A":
                    set_a = val
                else:
                    set_c = val
            except Exception:
                pass
    return set_a, set_c


def map_activities(generated, gold, mapped_out, mapping_model):
    a = extract_activity_names(generated)
    b = extract_activity_names(gold)
    mapping, set_c, table = get_alignment(a, b, model=mapping_model)
    revision_raw = get_revision(a, b, table, model=mapping_model)
    rev_a, rev_c = extract_python_lists(revision_raw)
    if rev_a is None:
        rev_a = a
    if rev_c is None:
        rev_c = set_c
    final_map = {x: (x if c.strip().lower().startswith("no") else c) for x, c in zip(rev_a, rev_c)}
    update_activity_names(generated, mapped_out, final_map)


def compare_bpmn(gold, mapped):
    comp = CompareBPMN(export_csv=False, export_excel=False)
    return comp.calculate_similarity(gold, mapped)


# ---------------------------
# Job building
# ---------------------------
def load_jobs(args):
    jobs = []

    if args.batch_manifest:
        with open(args.batch_manifest, "r", encoding="utf-8") as f:
            manifest = json.load(f)
        if not isinstance(manifest, list):
            raise ValueError("--batch-manifest must be a JSON list")

        for item in manifest:
            eid = item.get("id") or "noid"
            framework = item.get("framework")
            if framework not in ("ProMoAI", "MAO (AiO version)"):
                raise ValueError(f"Invalid or missing framework in manifest item: {framework}")

            runs = int(item.get("runs", 1))
            task_file = item.get("task_file")
            if not task_file:
                continue

            qbp = item.get("qbp") or _strip_eid_prefix(task_file, eid)

            for run_idx in range(1, runs + 1):
                job_id = f"{eid}:{qbp}:run{run_idx}"
                jobs.append({
                    "job_id": job_id,
                    "id": eid,
                    "qbp": qbp,
                    "framework": framework,
                    "run_idx": run_idx,
                    "task_file": task_file,
                    "gold_bpmn": item.get("gold_bpmn"),
                    "gold_bpmn_filename": item.get("gold_bpmn_filename"),
                    "name": item.get("name", "PipelineProject"),
                    "model": item.get("model", "GPT_5o2"),
                    "mapping_model": item.get("mapping_model", "gpt-5.2"),
                    "use_dedup": bool(item.get("use_dedup", False)),
                    "config": item.get("config"),
                    "org": item.get("org"),
                    "mapped_output": item.get("mapped_output"),
                })

        return jobs

    # Single mode (old behavior)
    if not args.framework or not args.task_file:
        raise ValueError("Single mode requires --framework and --task-file (or use --batch-manifest).")

    base = _stem(args.task_file)
    gold_fn = args.gold_bpmn_filename or (os.path.basename(args.gold_bpmn) if args.gold_bpmn else None)

    for run_idx in range(1, args.runs + 1):
        jobs.append({
            "job_id": f"single:{base}:run{run_idx}",
            "id": "single",
            "qbp": base,
            "framework": args.framework,
            "run_idx": run_idx,
            "task_file": args.task_file,
            "gold_bpmn": args.gold_bpmn,
            "gold_bpmn_filename": gold_fn,
            "name": args.name,
            "model": args.model,
            "mapping_model": args.mapping_model,
            "use_dedup": bool(args.use_dedup),
            "config": args.config,
            "org": args.org,
            "mapped_output": args.mapped_output,
        })
    return jobs


# ---------------------------
# Execute one job (NO DB writes here)
# ---------------------------
def run_one_job(job):
    eid = job["id"]
    qbp = job["qbp"]
    run_idx = job["run_idx"]
    framework = job["framework"]
    job_id = job["job_id"]

    jid = f"{job_id}"

    def jprint(msg: str):
        print(f"[{jid}] {msg}", flush=True)

    name_prefix = job.get("name") or "PipelineProject"
    model = job.get("model") or "GPT_5o2"
    mapping_model = job.get("mapping_model") or "gpt-5.2"
    task_file = job["task_file"]
    gold_bpmn = job.get("gold_bpmn")
    gold_bpmn_filename = job.get("gold_bpmn_filename")
    mapped_output_override = job.get("mapped_output")
    use_dedup = bool(job.get("use_dedup"))

    config = job.get("config")
    org = job.get("org")

    # Model identifier for DB / dashboard (optionally tag dedup runs)
    db_model = f"{model}_dedup" if use_dedup else model

    run_name = f"{name_prefix}_{qbp}_{eid}_run{run_idx}"
    jprint(f"=== Run {run_idx} for {qbp} ({framework}) ===")

    promoai_retries = None
    gen_bpmn = None

    # 1) Generate
    try:
        if framework == "MAO (AiO version)":
            if not config or not org:
                raise ValueError("MAO job missing config/org (set them in the UI card).")
            code_root = os.path.join("MAO", "MAO(AiO version)", "Code")
            gen_bpmn = run_mao(task_file, config, org, run_name, model, code_root)
        else:
            code_root = os.path.join("ProMoAI")
            gen_bpmn, promoai_retries = run_promoai(task_file, model, code_root, run_name)

    except subprocess.CalledProcessError as e:
        jprint("✗ Generation failed after all retries; skipping.")
        return {
            "job_id": job_id,
            "qbp": qbp,
            "framework_db": framework,
            "run_idx": run_idx,
            "status": "failed_generation",
            "error": "generation_failed_after_retries",
            "node_sim": None,
            "struct_sim": None,
            "ged": None,
            "gold_for_db": gold_bpmn_filename or (os.path.basename(gold_bpmn) if gold_bpmn else None),
            "gen_bpmn": None,
            "mapped_bpmn": None,
            "dedup_bpmn": None,
            "model": db_model,
            "promoai_retries": "failed" if framework == "ProMoAI" else None,
        }
    except Exception as e:
        jprint(f"✗ Job error: {e}")
        return {
            "job_id": job_id,
            "qbp": qbp,
            "framework_db": framework,
            "run_idx": run_idx,
            "status": "failed_error",
            "error": str(e),
            "node_sim": None,
            "struct_sim": None,
            "ged": None,
            "gold_for_db": gold_bpmn_filename or (os.path.basename(gold_bpmn) if gold_bpmn else None),
            "gen_bpmn": None,
            "mapped_bpmn": None,
            "dedup_bpmn": None,
            "model": db_model,
            "promoai_retries": promoai_retries if framework == "ProMoAI" else None,
        }

    # Adjust MAO output
    if framework == "MAO (AiO version)" and gen_bpmn:
        no_dummy_bpmn = gen_bpmn.replace("process.bpmn", "process_no_dummy.bpmn")
        if os.path.exists(no_dummy_bpmn):
            gen_bpmn = no_dummy_bpmn

    jprint(f"✔ Generated BPMN: {gen_bpmn}")

    # No gold: log generation only
    if not gold_bpmn:
        return {
            "job_id": job_id,
            "qbp": qbp,
            "framework_db": framework,
            "run_idx": run_idx,
            "status": "ok_no_gold",
            "error": None,
            "node_sim": None,
            "struct_sim": None,
            "ged": None,
            "gold_for_db": None,
            "gen_bpmn": gen_bpmn,
            "mapped_bpmn": None,
            "dedup_bpmn": None,
            "model": db_model,
            "promoai_retries": promoai_retries if framework == "ProMoAI" else None,
        }

    # 2) Map + 3) Optional duplicate handling + 4) Compare
    try:
        mapped_bpmn_for_db = None
        dedup_bpmn_for_db = None

        mapped = mapped_output_override or gen_bpmn.replace(".bpmn", "_mapped.bpmn")
        _safe_makedirs(os.path.dirname(mapped))
        map_activities(gen_bpmn, gold_bpmn, mapped, mapping_model)
        jprint(f"✔ Mapped  BPMN: {mapped}")
        mapped_bpmn_for_db = mapped

        mapped_for_compare = mapped
        if use_dedup:
            dedup_path = mapped.replace(".bpmn", "_dedup.bpmn")
            jprint(f"✔ Running duplicate handling on mapped BPMN: {mapped} → {dedup_path}")
            try:
                mapped_for_compare = remove_safe_duplicates(mapped, dedup_path)
                dedup_bpmn_for_db = mapped_for_compare
            except Exception as e:
                jprint(f"✗ Duplicate handling failed; continuing with original mapped BPMN. Error: {e}")
                mapped_for_compare = mapped

        node_sim, struct_sim, ged = compare_bpmn(gold_bpmn, mapped_for_compare)
        jprint(f"→ NodeSim={node_sim:.3f}, StructSim={struct_sim:.3f}, GED={ged}")

        # Framework formatting like your original code
        if framework == "ProMoAI":
            db_framework = "ProMoAI"
        else:
            db_framework = "MAO-v" + config.replace("Version-", "") if config else "MAO (AiO version)"

        return {
            "job_id": job_id,
            "qbp": qbp,
            "framework_db": db_framework,
            "run_idx": run_idx,
            "status": "ok",
            "error": None,
            "node_sim": node_sim,
            "struct_sim": struct_sim,
            "ged": ged,
            "gold_for_db": gold_bpmn_filename or os.path.basename(gold_bpmn),
            "gen_bpmn": gen_bpmn,
            "mapped_bpmn": mapped_bpmn_for_db,
            "dedup_bpmn": dedup_bpmn_for_db,
            "model": db_model,
            "promoai_retries": promoai_retries if framework == "ProMoAI" else None,
        }

    except Exception as e:
        jprint(f"✗ Post-process failed: {e}")

        if framework == "MAO (AiO version)" and config:
            db_framework = "MAO-v" + config.replace("Version-", "")
        else:
            db_framework = framework

        return {
            "job_id": job_id,
            "qbp": qbp,
            "framework_db": db_framework,
            "run_idx": run_idx,
            "status": "failed_postprocess",
            "error": str(e),
            "node_sim": None,
            "struct_sim": None,
            "ged": None,
            "gold_for_db": gold_bpmn_filename or os.path.basename(gold_bpmn),
            "gen_bpmn": gen_bpmn,
            "mapped_bpmn": mapped_bpmn_for_db if 'mapped_bpmn_for_db' in locals() else None,
            "dedup_bpmn": dedup_bpmn_for_db if 'dedup_bpmn_for_db' in locals() else None,
            "model": db_model,
            "promoai_retries": promoai_retries if framework == "ProMoAI" else None,
        }


# ---------------------------
# DB writer thread (single writer, crash-safe)
# ---------------------------
def db_writer_loop(db_path: str, batch_id: str, q: Queue):
    conn = db_connect(db_path)
    try:
        db_init(conn)
        while True:
            item = q.get()
            if item is None:
                break

            # item contains: {"type": "...", ...}
            t = item.get("type")

            if t == "started":
                db_mark_started(
                    conn,
                    batch_id=batch_id,
                    job_id=item["job_id"],
                    qbp=item["qbp"],
                    framework=item["framework"],
                    run_index=item["run_idx"],
                )

            elif t == "finished":
                # write the results row first (so it's present even if later update fails)
                db_insert_result(
                    conn,
                    qbp=item["qbp"],
                    framework=item["framework_db"],
                    node_sim=item["node_sim"],
                    struct_sim=item["struct_sim"],
                    ged=item["ged"],
                    gold=item["gold_for_db"],
                    gen=item["gen_bpmn"],
                    mapped=item.get("mapped_bpmn"),
                    dedup=item.get("dedup_bpmn"),
                    model=item["model"],
                    promoai_retries=item.get("promoai_retries"),
                )
                db_mark_finished(
                    conn,
                    batch_id=batch_id,
                    job_id=item["job_id"],
                    status=item["status"],
                    error=item.get("error"),
                )
            else:
                # ignore unknown messages
                pass

    finally:
        conn.close()


# ---------------------------
# Main
# ---------------------------
def main():
    args = parse_args()

    # batch id for grouping
    batch_id = args.batch_id or uuid.uuid4().hex
    print(f"BATCH_ID {batch_id}", flush=True)

    max_workers = int(args.max_workers or 1)
    if max_workers < 1:
        max_workers = 1

    jobs = load_jobs(args)
    total = len(jobs)
    if total == 0:
        print("No jobs to run.", flush=True)
        return

    print(
        f"Pipeline → jobs={total}, max_workers={max_workers}, results_db={args.results_db}, "
        f"PROMOAI_ENV={PROMOAI_ENV}, MAO_ENV={MAO_ENV}",
        flush=True,
    )

    # Start DB writer
    q = Queue()
    writer = Thread(target=db_writer_loop, args=(args.results_db, batch_id, q), daemon=True)
    writer.start()

    done = 0
    start_time = time.time()

    # Run jobs
    if max_workers == 1:
        for job in jobs:
            # mark started (in DB)
            q.put({"type": "started", "job_id": job["job_id"], "qbp": job["qbp"],
                   "framework": job["framework"], "run_idx": job["run_idx"]})

            r = run_one_job(job)
            q.put({"type": "finished", **r})

            done += 1
            print(f"PROGRESS {done}/{total}", flush=True)

    else:
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            future_to_job = {}

            # submit all jobs; mark started in DB as they are submitted
            for job in jobs:
                q.put({"type": "started", "job_id": job["job_id"], "qbp": job["qbp"],
                       "framework": job["framework"], "run_idx": job["run_idx"]})
                fut = ex.submit(run_one_job, job)
                future_to_job[fut] = job

            # as jobs finish, write to DB + progress
            for fut in as_completed(future_to_job):
                r = fut.result()
                q.put({"type": "finished", **r})

                done += 1
                print(f"PROGRESS {done}/{total}", flush=True)

    # stop writer
    q.put(None)
    writer.join()

    elapsed = time.time() - start_time
    print(f"DONE {done}/{total} in {elapsed:.2f}s", flush=True)


if __name__ == "__main__":
    main()
