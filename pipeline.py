#!/usr/bin/env python3
# pipeline.py
"""
Unified pipeline for MAO (AiO version) and ProMoAI frameworks.

Key features:
  - Batch mode via --batch-manifest (JSON from Streamlit UI)
  - Parallel execution via --max-workers (dynamic retry-aware)
  - Dual similarity metrics: pre-dedup AND post-dedup when --use-dedup
  - Retry logic: --only-successful retries failed runs until target successes reached
  - Incremental DB writes (crash-safe WAL mode)
  - Progress lines parsed by Streamlit: PROGRESS X/Y [attempts=Z]

Manifest item format:
{
  "id": "a1b2c3d4",          # experiment id
  "framework": "ProMoAI" | "MAO (AiO version)",
  "runs": 5,                 # target runs (successful ones if only_successful)
  "name": "PipelineRun",
  "model": "GPT_5o2",
  "mapping_model": "gpt-5.2",
  "use_dedup": false,        # compute similarity both before & after dedup
  "only_successful": false,  # retry failed runs to hit target
  "max_retry_multiplier": 3.0,
  "config": "Version-3.8",   # MAO only
  "org": "Version-3.8",      # MAO only
  "task_file": "/tmp/id__QBP1.txt",
  "gold_bpmn": "/tmp/id__QBP1.bpmn" | null,
  "gold_bpmn_filename": "QBP1.bpmn" | null
}
"""

import argparse
import copy
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
import uuid
from collections import deque
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from queue import Queue
from threading import Thread

# ── Env config ────────────────────────────────────────────────────────────────
PROMOAI_ENV = os.environ.get("PROMOAI_ENV", "promoai")
MAO_ENV     = os.environ.get("MAO_ENV",     "mao")

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


# ════════════════════════════════════════════════════════════════════════════
# Args
# ════════════════════════════════════════════════════════════════════════════

def parse_args():
    p = argparse.ArgumentParser(
        description="BPMN generation + similarity pipeline (batch & single mode)."
    )
    # Batch
    p.add_argument("--batch-manifest", default=None,
                   help="JSON list of experiment items (from Streamlit UI).")
    p.add_argument("--max-workers", type=int, default=1,
                   help="Parallel worker threads.")
    p.add_argument("--batch-id", default=None,
                   help="Optional batch grouping id; auto-generated if omitted.")
    p.add_argument("--results-db", default="resultsDb.sqlite",
                   help="SQLite database path.")

    # Retry / reliability
    p.add_argument("--only-successful", action="store_true",
                   help="Retry failed runs until target successes are reached.")
    p.add_argument("--max-retry-multiplier", type=float, default=3.0,
                   help="max_attempts = target_runs * multiplier (default 3.0).")

    # Single-mode (backwards compatible)
    p.add_argument("--framework", choices=["ProMoAI", "MAO (AiO version)"])
    p.add_argument("--task-file")
    p.add_argument("--gold-bpmn")
    p.add_argument("--runs", type=int, default=1)
    p.add_argument("--config", default=None)
    p.add_argument("--org",    default=None)
    p.add_argument("--name",   default="PipelineProject")
    p.add_argument("--model",  default="GPT_5o2")
    p.add_argument("--mapped-output", default=None)
    p.add_argument("--gold-bpmn-filename", default=None)
    p.add_argument("--mapping-model", default="gpt-5.2")
    p.add_argument("--use-dedup", action="store_true",
                   help="Compute similarity both before AND after dedup.")

    return p.parse_args()


# ════════════════════════════════════════════════════════════════════════════
# Database helpers
# ════════════════════════════════════════════════════════════════════════════

def db_connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA busy_timeout=30000;")
    conn.row_factory = sqlite3.Row
    return conn


def db_init(conn: sqlite3.Connection):
    c = conn.cursor()

    # ── runs: one row per generation attempt ─────────────────────────────────
    c.execute("""
    CREATE TABLE IF NOT EXISTS runs (
        id                  INTEGER PRIMARY KEY AUTOINCREMENT,
        batch_id            TEXT    NOT NULL,
        job_id              TEXT    NOT NULL,
        timestamp           TEXT,
        qbp_name            TEXT,
        framework           TEXT,
        model               TEXT,
        attempt_number      INTEGER,
        status              TEXT,           -- ok | ok_no_gold | failed_generation |
                                            -- failed_mapping | failed_similarity | failed_error
        error               TEXT,
        elapsed_seconds     REAL,

        -- Artefact paths
        gold_bpmn           TEXT,
        generated_bpmn      TEXT,
        mapped_bpmn         TEXT,

        -- Pre-dedup similarity (always computed when gold BPMN provided)
        node_sim            REAL,
        struct_sim          REAL,
        ged                 INTEGER,

        -- Post-dedup similarity (only when use_dedup = 1)
        use_dedup           INTEGER DEFAULT 0,
        dedup_bpmn          TEXT,
        node_sim_dedup      REAL,
        struct_sim_dedup    REAL,
        ged_dedup           INTEGER,

        promoai_retries     TEXT,

        UNIQUE(batch_id, job_id)
    )""")

    # ── batches: one row per pipeline invocation ─────────────────────────────
    c.execute("""
    CREATE TABLE IF NOT EXISTS batches (
        batch_id        TEXT PRIMARY KEY,
        started_at      TEXT,
        finished_at     TEXT,
        status          TEXT,
        total_target    INTEGER,
        total_attempts  INTEGER,
        total_successes INTEGER,
        results_db      TEXT
    )""")

    # Keep the legacy table for any existing tooling.
    c.execute("""
    CREATE TABLE IF NOT EXISTS experiment_results (
        id                      INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp               TEXT,
        qbp_name                TEXT,
        framework               TEXT,
        node_similarity         REAL,
        structure_similarity    REAL,
        graph_edit_distance     INTEGER,
        gold_bpmn_path          TEXT,
        generated_bpmn_path     TEXT,
        model                   TEXT,
        promoai_retries         TEXT
    )""")

    conn.commit()


def db_upsert_run(conn: sqlite3.Connection, r: dict):
    conn.execute("""
    INSERT OR REPLACE INTO runs (
        batch_id, job_id, timestamp,
        qbp_name, framework, model, attempt_number,
        status, error, elapsed_seconds,
        gold_bpmn, generated_bpmn, mapped_bpmn,
        node_sim, struct_sim, ged,
        use_dedup, dedup_bpmn, node_sim_dedup, struct_sim_dedup, ged_dedup,
        promoai_retries
    ) VALUES (
        :batch_id, :job_id, datetime('now'),
        :qbp_name, :framework, :model, :attempt_number,
        :status, :error, :elapsed_seconds,
        :gold_bpmn, :generated_bpmn, :mapped_bpmn,
        :node_sim, :struct_sim, :ged,
        :use_dedup, :dedup_bpmn, :node_sim_dedup, :struct_sim_dedup, :ged_dedup,
        :promoai_retries
    )""", r)
    conn.commit()


def db_batch_start(conn: sqlite3.Connection, batch_id: str, total_target: int):
    conn.execute("""
    INSERT OR IGNORE INTO batches (batch_id, started_at, status, total_target)
    VALUES (?, datetime('now'), 'running', ?)
    """, (batch_id, total_target))
    conn.commit()


def db_batch_finish(conn: sqlite3.Connection, batch_id: str,
                    total_attempts: int, total_successes: int):
    conn.execute("""
    UPDATE batches
    SET status='finished', finished_at=datetime('now'),
        total_attempts=?, total_successes=?
    WHERE batch_id=?
    """, (total_attempts, total_successes, batch_id))
    conn.commit()


# ════════════════════════════════════════════════════════════════════════════
# Misc helpers
# ════════════════════════════════════════════════════════════════════════════

def _stem(path: str) -> str:
    return os.path.splitext(os.path.basename(path))[0]


def _safe_makedirs(path: str):
    if path:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)


def _conda_prefix(env_name: str):
    conda_exe = shutil.which("conda")
    if conda_exe:
        return [conda_exe, "run", "--no-capture-output", "-n", env_name, "python", "-u"]
    return None


def _strip_eid_prefix(filename: str, eid: str) -> str:
    base   = os.path.basename(filename)
    prefix = f"{eid}__"
    if base.startswith(prefix):
        base = base[len(prefix):]
    return os.path.splitext(base)[0]


# ════════════════════════════════════════════════════════════════════════════
# Framework runners  (no logic changes — only robustness / timeout)
# ════════════════════════════════════════════════════════════════════════════

def run_mao(task_file: str, config: str, org: str,
            name: str, model: str, code_root: str,
            timeout: int = 900) -> str:
    script = os.path.join(code_root, "run.py")
    prefix = _conda_prefix(MAO_ENV) or [sys.executable, "-u"]
    cmd = prefix + [
        script,
        "--task-file", task_file,
        "--config", config,
        "--org", org,
        "--name", name,
    ]
    if model:
        cmd += ["--model", model]

    result = subprocess.run(
        cmd,
        check=True,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    output_lines = result.stdout.strip().splitlines()
    if not output_lines:
        raise RuntimeError("MAO produced no output.")
    return output_lines[-1]


def run_gpt_direct(task_file: str, model: str, code_root: str,
                   project_name: str, retry_mode: str = "full",
                   timeout: int = None):
    """
    Run the GPT Direct framework — calls gpt_direct_api.py as a subprocess.
    retry_mode ∈ {"none", "repair", "full"}.
    Returns (bpmn_path: str, retries_summary: str).

    timeout is intentionally None by default: gpt_direct_api.py applies its
    own per-call API timeout (1 hour) which is the correct governing limit.
    Reasoning models (gpt-5.4 xhigh) can legitimately take 20–60 min per call,
    so a subprocess-level timeout would fire before the model finishes.
    """
    script = os.path.join(code_root, "gpt_direct_api.py")
    if not os.path.exists(script):
        raise FileNotFoundError(
            f"gpt_direct_api.py not found at {script}. "
            "Place gpt_direct_api.py in the repo root."
        )

    cmd = [
        sys.executable, "-u", script,
        "--task-file",    task_file,
        "--model",        model,
        "--output-dir",   "GPTDirectOutput",
        "--project-name", project_name,
        "--retry-mode",   retry_mode,
    ]

    result = subprocess.run(
        cmd,
        check=True,
        capture_output=True,
        text=True,
        timeout=timeout,   # None = no subprocess-level timeout
    )

    gpt_retries = None
    bpmn_path   = None
    for line in result.stdout.strip().splitlines():
        if line.startswith("GPT_DIRECT_RETRIES:"):
            gpt_retries = line.split("GPT_DIRECT_RETRIES:", 1)[1].strip()
        elif line.endswith(".bpmn"):
            bpmn_path = line.strip()

    return bpmn_path, gpt_retries


def run_promoai(task_file: str, model: str, code_root: str,
                project_name: str, timeout: int = 900):
    prefix = _conda_prefix(PROMOAI_ENV)
    if prefix is None:
        raise RuntimeError("conda not found on PATH; ProMoAI requires the conda environment.")

    cmd = prefix + [
        "ProMoAI_API.py",
        "--task-file",    task_file,
        "--model",        model,
        "--output-dir",   "WareHouse",
        "--project-name", project_name,
    ]

    result = subprocess.run(
        cmd,
        cwd=code_root,
        check=True,
        capture_output=True,
        text=True,
        timeout=timeout,
    )

    promoai_retries = None
    bpmn_path       = None
    for line in result.stdout.strip().splitlines():
        if line.startswith("PROMOAI_RETRIES:"):
            promoai_retries = line.split("PROMOAI_RETRIES:", 1)[1].strip()
        elif line.endswith(".bpmn"):
            bpmn_path = line

    return bpmn_path, promoai_retries


# ════════════════════════════════════════════════════════════════════════════
# Activity mapping + similarity comparison
# ════════════════════════════════════════════════════════════════════════════

def _extract_python_lists(text: str):
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


def map_activities(generated: str, gold: str, mapped_out: str, mapping_model: str):
    a = extract_activity_names(generated)
    b = extract_activity_names(gold)
    _mapping, set_c, table = get_alignment(a, b, model=mapping_model)
    revision_raw = get_revision(a, b, table, model=mapping_model)
    rev_a, rev_c = _extract_python_lists(revision_raw)
    if rev_a is None:
        rev_a = a
    if rev_c is None:
        rev_c = set_c
    final_map = {
        x: (x if c.strip().lower().startswith("no") else c)
        for x, c in zip(rev_a, rev_c)
    }
    update_activity_names(generated, mapped_out, final_map)


def compare_bpmn(gold: str, candidate: str):
    comp = CompareBPMN(export_csv=False, export_excel=False)
    return comp.calculate_similarity(gold, candidate)


# ════════════════════════════════════════════════════════════════════════════
# Job building
# ════════════════════════════════════════════════════════════════════════════

def _make_job(eid, qbp, framework, run_idx, task_file, gold_bpmn,
              gold_bpmn_filename, name, model, mapping_model,
              use_dedup, only_successful, max_retry_multiplier,
              target_runs, config, org, mapped_output,
              gpt_direct_retry_mode="full") -> dict:
    return {
        "job_id":                   f"{eid}:{qbp}:attempt{run_idx}",
        "id":                       eid,
        "qbp":                      qbp,
        "framework":                framework,
        "run_idx":                  run_idx,
        "task_file":                task_file,
        "gold_bpmn":                gold_bpmn,
        "gold_bpmn_filename":       gold_bpmn_filename,
        "name":                     name,
        "model":                    model,
        "mapping_model":            mapping_model,
        "use_dedup":                use_dedup,
        "only_successful":          only_successful,
        "max_retry_multiplier":     max_retry_multiplier,
        "target_runs":              target_runs,
        "config":                   config,
        "org":                      org,
        "mapped_output":            mapped_output,
        "gpt_direct_retry_mode":    gpt_direct_retry_mode,
    }


def make_retry_job(original_job: dict, attempt_idx: int) -> dict:
    j = copy.deepcopy(original_job)
    j["run_idx"] = attempt_idx
    j["job_id"]  = f"{original_job['id']}:{original_job['qbp']}:attempt{attempt_idx}"
    return j


def load_jobs(args) -> list:
    jobs: list = []

    if args.batch_manifest:
        with open(args.batch_manifest, "r", encoding="utf-8") as f:
            manifest = json.load(f)
        if not isinstance(manifest, list):
            raise ValueError("--batch-manifest must be a JSON array.")

        for item in manifest:
            eid       = item.get("id") or "noid"
            framework = item.get("framework", "")
            if framework not in ("ProMoAI", "MAO (AiO version)", "GPT Direct"):
                raise ValueError(f"Invalid framework in manifest: {framework!r}")

            task_file = item.get("task_file")
            if not task_file:
                continue

            target_runs = int(item.get("runs", 1))
            qbp = item.get("qbp") or _strip_eid_prefix(task_file, eid)

            # Per-manifest item overrides; fall back to global args
            only_succ = item.get("only_successful", args.only_successful)
            mult      = item.get("max_retry_multiplier", args.max_retry_multiplier)

            for run_idx in range(1, target_runs + 1):
                jobs.append(_make_job(
                    eid=eid, qbp=qbp, framework=framework,
                    run_idx=run_idx, task_file=task_file,
                    gold_bpmn=item.get("gold_bpmn"),
                    gold_bpmn_filename=item.get("gold_bpmn_filename"),
                    name=item.get("name", "PipelineProject"),
                    model=item.get("model", "GPT_5o2"),
                    mapping_model=item.get("mapping_model", "gpt-5.2"),
                    use_dedup=bool(item.get("use_dedup", False)),
                    only_successful=only_succ,
                    max_retry_multiplier=mult,
                    target_runs=target_runs,
                    config=item.get("config"),
                    org=item.get("org"),
                    mapped_output=item.get("mapped_output"),
                    gpt_direct_retry_mode=item.get("gpt_direct_retry_mode", "full"),
                ))
        return jobs

    # ── Single mode ────────────────────────────────────────────────────────
    if not args.framework or not args.task_file:
        raise ValueError("Single mode requires --framework and --task-file.")

    if args.framework not in ("ProMoAI", "MAO (AiO version)", "GPT Direct"):
        raise ValueError(f"Unknown framework: {args.framework!r}")

    base    = _stem(args.task_file)
    gold_fn = (args.gold_bpmn_filename
               or (os.path.basename(args.gold_bpmn) if args.gold_bpmn else None))

    for run_idx in range(1, args.runs + 1):
        jobs.append(_make_job(
            eid="single", qbp=base, framework=args.framework,
            run_idx=run_idx, task_file=args.task_file,
            gold_bpmn=args.gold_bpmn, gold_bpmn_filename=gold_fn,
            name=args.name, model=args.model,
            mapping_model=args.mapping_model,
            use_dedup=args.use_dedup,
            only_successful=args.only_successful,
            max_retry_multiplier=args.max_retry_multiplier,
            target_runs=args.runs,
            config=args.config, org=args.org,
            mapped_output=args.mapped_output,
            gpt_direct_retry_mode=getattr(args, "gpt_direct_retry_mode", "full"),
        ))
    return jobs


# ════════════════════════════════════════════════════════════════════════════
# Execute one job
# Returns a result dict; does NOT touch the DB.
# ════════════════════════════════════════════════════════════════════════════

def run_one_job(job: dict) -> dict:
    t0          = time.time()
    eid         = job["id"]
    qbp         = job["qbp"]
    run_idx     = job["run_idx"]
    framework   = job["framework"]
    job_id      = job["job_id"]
    use_dedup   = bool(job.get("use_dedup"))

    def jprint(msg: str):
        print(f"[{job_id}] {msg}", flush=True)

    name_prefix     = job.get("name")          or "PipelineProject"
    model           = job.get("model")         or "GPT_5o2"
    mapping_model   = job.get("mapping_model") or "gpt-5.2"
    task_file       = job["task_file"]
    gold_bpmn       = job.get("gold_bpmn")
    gold_bpmn_fn    = job.get("gold_bpmn_filename")
    mapped_override = job.get("mapped_output")
    config          = job.get("config")
    org             = job.get("org")

    # DB model label: tag dedup runs so they're distinguishable in results
    db_model  = f"{model}_dedup" if use_dedup else model
    run_name  = f"{name_prefix}_{qbp}_{eid}_attempt{run_idx}"

    jprint(f"=== Attempt {run_idx} for '{qbp}' [{framework}] use_dedup={use_dedup} ===")

    promoai_retries = None
    gen_bpmn        = None

    # ── Scaffold for early-exit returns ─────────────────────────────────────
    def _result(status: str, error: str = None) -> dict:
        return {
            "job_id":           job_id,
            "qbp_name":         qbp,
            "framework":        framework,
            "model":            db_model,
            "attempt_number":   run_idx,
            "status":           status,
            "error":            error,
            "elapsed_seconds":  round(time.time() - t0, 2),
            "gold_bpmn":        gold_bpmn_fn or (os.path.basename(gold_bpmn) if gold_bpmn else None),
            "generated_bpmn":   gen_bpmn,
            "mapped_bpmn":      None,
            "node_sim":         None,
            "struct_sim":       None,
            "ged":              None,
            "use_dedup":        int(use_dedup),
            "dedup_bpmn":       None,
            "node_sim_dedup":   None,
            "struct_sim_dedup": None,
            "ged_dedup":        None,
            "promoai_retries":  promoai_retries,
        }

    # ── Step 1: Generate BPMN ─────────────────────────────────────────────
    try:
        if framework == "MAO (AiO version)":
            if not config or not org:
                raise ValueError("MAO experiment is missing 'config' and/or 'org'.")
            code_root = os.path.join("MAO", "MAO(AiO version)", "Code")
            gen_bpmn  = run_mao(task_file, config, org, run_name, model, code_root)
        elif framework == "GPT Direct":
            retry_mode = job.get("gpt_direct_retry_mode", "full")
            code_root  = os.path.dirname(os.path.abspath(__file__))
            gen_bpmn, promoai_retries = run_gpt_direct(
                task_file, model, code_root, run_name, retry_mode=retry_mode
            )
        else:
            code_root = os.path.join("ProMoAI")
            gen_bpmn, promoai_retries = run_promoai(task_file, model, code_root, run_name)

    except subprocess.CalledProcessError as e:
        stderr = (e.stderr or "").strip()
        jprint(f"✗ Generation subprocess failed:\n{stderr or '(no stderr)'}")
        return _result("failed_generation", f"subprocess_error: {stderr}")
    except subprocess.TimeoutExpired:
        jprint("✗ Generation timed out.")
        return _result("failed_generation", "timeout")
    except Exception as e:
        jprint(f"✗ Generation error: {e}")
        return _result("failed_generation", str(e))

    # MAO: prefer the no-dummy variant when available
    if framework == "MAO (AiO version)" and gen_bpmn:
        nd = gen_bpmn.replace("process.bpmn", "process_no_dummy.bpmn")
        if os.path.exists(nd):
            gen_bpmn = nd

    if not gen_bpmn or not os.path.exists(gen_bpmn):
        jprint("✗ Generated BPMN path is missing or does not exist.")
        return _result("failed_generation", "bpmn_file_not_found")

    jprint(f"✔ Generated: {gen_bpmn}")

    # Determine framework label for DB
    if framework == "MAO (AiO version)" and config:
        framework_db = "MAO-v" + config.replace("Version-", "")
    elif framework == "GPT Direct":
        retry_mode   = job.get("gpt_direct_retry_mode", "full")
        framework_db = f"GPT-Direct-{retry_mode}"
    else:
        framework_db = framework

    # No gold BPMN → log generation only, no similarity
    if not gold_bpmn:
        r = _result("ok_no_gold")
        r["framework"]       = framework_db
        r["generated_bpmn"]  = gen_bpmn
        r["promoai_retries"] = promoai_retries if framework in ("ProMoAI", "GPT Direct") else None
        return r

    # ── Step 2: Activity mapping ──────────────────────────────────────────
    mapped_bpmn = None
    try:
        mapped = mapped_override or gen_bpmn.replace(".bpmn", "_mapped.bpmn")
        _safe_makedirs(mapped)
        map_activities(gen_bpmn, gold_bpmn, mapped, mapping_model)
        if not os.path.exists(mapped):
            raise FileNotFoundError(f"Mapped BPMN not created at: {mapped}")
        mapped_bpmn = mapped
        jprint(f"✔ Mapped:    {mapped}")
    except Exception as e:
        jprint(f"✗ Activity mapping failed: {e}")
        r = _result("failed_mapping", str(e))
        r["framework"]       = framework_db
        r["generated_bpmn"]  = gen_bpmn
        r["promoai_retries"] = promoai_retries if framework in ("ProMoAI", "GPT Direct") else None
        return r

    # ── Step 3: Pre-dedup similarity ─────────────────────────────────────
    node_sim = struct_sim = ged = None
    try:
        node_sim, struct_sim, ged = compare_bpmn(gold_bpmn, mapped_bpmn)
        jprint(f"→ Pre-dedup  : NodeSim={node_sim:.3f}  StructSim={struct_sim:.3f}  GED={ged}")
    except Exception as e:
        jprint(f"✗ Pre-dedup similarity failed: {e}")
        r = _result("failed_similarity", str(e))
        r["framework"]       = framework_db
        r["generated_bpmn"]  = gen_bpmn
        r["mapped_bpmn"]     = mapped_bpmn
        r["promoai_retries"] = promoai_retries if framework == "ProMoAI" else None
        return r

    # ── Step 4 (optional): Dedup + post-dedup similarity ─────────────────
    dedup_bpmn = node_sim_d = struct_sim_d = ged_d = None
    if use_dedup:
        try:
            dedup_path = mapped_bpmn.replace(".bpmn", "_dedup.bpmn")
            remove_safe_duplicates(mapped_bpmn, dedup_path)
            if not os.path.exists(dedup_path):
                raise FileNotFoundError(f"Dedup BPMN not created at: {dedup_path}")
            node_sim_d, struct_sim_d, ged_d = compare_bpmn(gold_bpmn, dedup_path)
            dedup_bpmn = dedup_path
            jprint(f"→ Post-dedup : NodeSim={node_sim_d:.3f}  StructSim={struct_sim_d:.3f}  GED={ged_d}")
        except Exception as e:
            # Dedup failure is non-fatal: we keep pre-dedup scores and note the error
            jprint(f"⚠ Dedup/post-similarity failed (pre-dedup scores retained): {e}")

    # ── All done ─────────────────────────────────────────────────────────
    return {
        "job_id":           job_id,
        "qbp_name":         qbp,
        "framework":        framework_db,
        "model":            db_model,
        "attempt_number":   run_idx,
        "status":           "ok",
        "error":            None,
        "elapsed_seconds":  round(time.time() - t0, 2),
        "gold_bpmn":        gold_bpmn_fn or os.path.basename(gold_bpmn),
        "generated_bpmn":   gen_bpmn,
        "mapped_bpmn":      mapped_bpmn,
        "node_sim":         node_sim,
        "struct_sim":       struct_sim,
        "ged":              ged,
        "use_dedup":        int(use_dedup),
        "dedup_bpmn":       dedup_bpmn,
        "node_sim_dedup":   node_sim_d,
        "struct_sim_dedup": struct_sim_d,
        "ged_dedup":        ged_d,
        "promoai_retries":  promoai_retries if framework == "ProMoAI" else None,
    }


# ════════════════════════════════════════════════════════════════════════════
# DB writer thread (single serialised writer — crash-safe)
# ════════════════════════════════════════════════════════════════════════════

def db_writer_loop(db_path: str, batch_id: str, total_target: int, q: Queue):
    conn = db_connect(db_path)
    try:
        db_init(conn)
        db_batch_start(conn, batch_id, total_target)
        attempts  = 0
        successes = 0
        while True:
            item = q.get()
            if item is None:
                break
            r = item.get("result")
            if not r:
                continue
            r = dict(r)
            r["batch_id"] = batch_id
            try:
                db_upsert_run(conn, r)
                attempts += 1
                if r.get("status") == "ok":
                    successes += 1
            except Exception as e:
                print(f"[DB] Write error: {e}", flush=True)
    finally:
        try:
            db_batch_finish(conn, batch_id, attempts, successes)
        except Exception:
            pass
        conn.close()


# ════════════════════════════════════════════════════════════════════════════
# Per-experiment retry state
# ════════════════════════════════════════════════════════════════════════════

def build_exp_state(jobs: list) -> dict:
    state: dict = {}
    for job in jobs:
        eid = job["id"]
        if eid not in state:
            target = job["target_runs"]
            mult   = max(float(job.get("max_retry_multiplier", 3.0)), 1.0)
            state[eid] = {
                "qbp":            job["qbp"],
                "target":         target,
                "only_succ":      bool(job.get("only_successful", False)),
                "max_attempts":   max(int(target * mult), target + 1),
                "successes":      0,
                "attempts":       0,
                "next_attempt":   target + 1,   # next run_idx for retry jobs
                "base_job":       job,
            }
    return state


def _is_success(r: dict) -> bool:
    return r.get("status") in ("ok", "ok_no_gold")


# ════════════════════════════════════════════════════════════════════════════
# Progress reporting
# ════════════════════════════════════════════════════════════════════════════

def _progress_line(exp_state: dict, done_attempts: int, total_attempts: int) -> str:
    """
    When any experiment uses only_successful mode, report progress as
    successes / total-target so the Streamlit bar shows meaningful progress.
    Otherwise report attempts / total.
    """
    any_only_succ = any(s["only_succ"] for s in exp_state.values())
    if any_only_succ:
        total_succ = sum(s["successes"] for s in exp_state.values())
        total_tgt  = sum(s["target"]    for s in exp_state.values())
        return f"PROGRESS {total_succ}/{total_tgt} attempts={done_attempts}"
    return f"PROGRESS {done_attempts}/{total_attempts}"


# ════════════════════════════════════════════════════════════════════════════
# Main
# ════════════════════════════════════════════════════════════════════════════

def main():
    args     = parse_args()
    batch_id = args.batch_id or uuid.uuid4().hex
    print(f"BATCH_ID {batch_id}", flush=True)

    max_workers = max(int(args.max_workers or 1), 1)
    jobs        = load_jobs(args)

    if not jobs:
        print("No jobs found — check your manifest.", flush=True)
        return

    total_target = sum(
        j["target_runs"]
        for j in {j["id"]: j for j in jobs}.values()  # unique per experiment
    )
    total = len(jobs)   # grows if retries are added

    exp_state = build_exp_state(jobs)

    print(
        f"Pipeline → initial_jobs={total}  max_workers={max_workers}  "
        f"db={args.results_db}  only_successful={args.only_successful}",
        flush=True,
    )

    # Start background DB writer
    q      = Queue()
    writer = Thread(
        target=db_writer_loop,
        args=(args.results_db, batch_id, total_target, q),
        daemon=True,
    )
    writer.start()

    done_attempts = 0
    wall_start    = time.time()

    # ── Helper: process a completed result ────────────────────────────────
    def handle_result(job: dict, r: dict) -> "dict | None":
        """
        Emit result to DB queue, update exp_state.
        Returns a retry job if one is needed, else None.
        """
        nonlocal done_attempts, total
        q.put({"result": r})
        done_attempts += 1

        eid   = job["id"]
        state = exp_state.get(eid)
        if not state:
            return None

        state["attempts"] += 1
        success = _is_success(r)
        if success:
            state["successes"] += 1

        print(_progress_line(exp_state, done_attempts, total), flush=True)

        # Should we retry?
        if (state["only_succ"]
                and not success
                and state["successes"] < state["target"]
                and state["attempts"]  < state["max_attempts"]):

            attempt_idx = state["next_attempt"]
            state["next_attempt"] += 1
            retry = make_retry_job(state["base_job"], attempt_idx)
            total += 1
            print(
                f"RETRY {state['qbp']} "
                f"(successes={state['successes']}/{state['target']} "
                f" attempts={state['attempts']}/{state['max_attempts']} "
                f" queuing attempt {attempt_idx})",
                flush=True,
            )
            return retry
        return None

    # ── Serial execution ──────────────────────────────────────────────────
    if max_workers == 1:
        pending = deque(jobs)
        while pending:
            job   = pending.popleft()
            r     = run_one_job(job)
            retry = handle_result(job, r)
            if retry:
                pending.append(retry)

    # ── Parallel execution ────────────────────────────────────────────────
    else:
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            futures: dict = {ex.submit(run_one_job, job): job for job in jobs}

            while futures:
                # wait() supports dynamically-added futures correctly
                done_set, _ = wait(list(futures.keys()), return_when=FIRST_COMPLETED)

                for done_fut in done_set:
                    job = futures.pop(done_fut)
                    try:
                        r = done_fut.result()
                    except Exception as exc:
                        # Wrap unexpected thread-level exceptions
                        r = {
                            "job_id":           job["job_id"],
                            "qbp_name":         job["qbp"],
                            "framework":        job["framework"],
                            "model":            job.get("model", ""),
                            "attempt_number":   job["run_idx"],
                            "status":           "failed_error",
                            "error":            str(exc),
                            "elapsed_seconds":  0,
                            "gold_bpmn":        None,
                            "generated_bpmn":   None,
                            "mapped_bpmn":      None,
                            "node_sim":         None,
                            "struct_sim":       None,
                            "ged":              None,
                            "use_dedup":        int(job.get("use_dedup", False)),
                            "dedup_bpmn":       None,
                            "node_sim_dedup":   None,
                            "struct_sim_dedup": None,
                            "ged_dedup":        None,
                            "promoai_retries":  None,
                        }

                    retry = handle_result(job, r)
                    if retry:
                        new_fut = ex.submit(run_one_job, retry)
                        futures[new_fut] = retry

    # ── Shutdown ──────────────────────────────────────────────────────────
    q.put(None)
    writer.join()

    elapsed       = time.time() - wall_start
    total_succ    = sum(s["successes"] for s in exp_state.values())
    total_tgt_all = sum(s["target"]    for s in exp_state.values())

    print(
        f"DONE successes={total_succ}/{total_tgt_all} "
        f"attempts={done_attempts} elapsed={elapsed:.2f}s",
        flush=True,
    )


if __name__ == "__main__":
    main()