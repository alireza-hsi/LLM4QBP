#!/usr/bin/env python3
"""
Unified pipeline for MAO-* and ProMoAI frameworks,
including activity mapping, BPMN comparison, and
skipping/logging runs that fail all retries.
"""
import argparse
import os
import sys
import subprocess
import sqlite3

# Ensure your MAO helpers are on PYTHONPATH
MAO_HELPER = os.path.join("MAO", "Code", "Helper")
sys.path.insert(0, MAO_HELPER)

from automatedActivityMapping import extract_activity_names, get_alignment, get_revision, update_activity_names
from bpmn_compare_similarity import CompareBPMN

def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--framework",
                   choices=["MAO-v2.2","ProMoAI"],
                   required=True)
    p.add_argument("--task-file",   required=True)
    p.add_argument("--gold-bpmn",   required=True)
    p.add_argument("--runs",  type=int, default=1)
    p.add_argument("--config", default="Default")
    p.add_argument("--org",    default="DefaultOrganization")
    p.add_argument("--name",   default="PipelineProject")
    p.add_argument("--model",  default="GPT_4o1",
                   help="Always use GPT_4o1 for analytics")
    p.add_argument("--mapped-output", default=None)
    p.add_argument("--results-db",    default="resultsDb.sqlite")
    p.add_argument("--gold-bpmn-filename", default=None)
    return p.parse_args()

def log_results(db, qbp, framework, node_sim, struct_sim, ged, gold, gen, model, promoai_retries=None):
    conn = sqlite3.connect(db)
    c = conn.cursor()
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
    c.execute("""
      INSERT INTO experiment_results (
        timestamp, qbp_name, framework,
        node_similarity, structure_similarity, graph_edit_distance,
        gold_bpmn_path, generated_bpmn_path, model, promoai_retries
      ) VALUES (datetime('now'),?,?,?,?,?,?,?, ?, ?)
    """, (qbp, framework, node_sim, struct_sim, ged, gold, gen, model, promoai_retries))
    conn.commit()
    conn.close()

def run_mao(task_file, config, org, name, model, code_root):
    script = os.path.join(code_root, "run.py")
    cmd = [sys.executable, script,
           "--task-file", task_file,
           "--config",    config,
           "--org",       org,
           "--name",      name]
    if model:
        cmd += ["--model", model]
    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        print("Error running MAO run.py:", e)
        print("STDOUT:", e.stdout)
        print("STDERR:", e.stderr)
        raise
    bpmn_path = result.stdout.strip().splitlines()[-1]
    return bpmn_path

def run_promoai(task_file, model, code_root, project_name):
    script = "ProMoAI_API.py"
    cmd = [
        "conda", "run", "-n", "base", "python",
        script,
        "--task-file",    task_file,
        "--model",        model,
        "--output-dir",   "WareHouse",
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
    # Fix: Join with code_root if path is relative
    if bpmn_path and not os.path.isabs(bpmn_path):
        bpmn_path = os.path.join(code_root, bpmn_path)
    return bpmn_path, promoai_retries

def extract_python_lists(text):
    import re, ast
    set_a = set_c = None
    for var in ("Set_A","Set_C"):
        m = re.search(rf"{var}\s*=\s*(\[[\s\S]*?\])", text)
        if m:
            try:
                val = ast.literal_eval(m.group(1))
                if var=="Set_A": set_a = val
                else:           set_c = val
            except:
                pass
    return set_a, set_c

def map_activities(generated, gold, mapped_out):
    a = extract_activity_names(generated)
    b = extract_activity_names(gold)
    mapping, set_c, table = get_alignment(a, b)
    rev_a, rev_c = extract_python_lists(get_revision(a, b, table))
    if rev_a is None: rev_a = a
    if rev_c is None: rev_c = set_c
    final_map = {
      x: (x if c.strip().lower().startswith("no") else c)
      for x,c in zip(rev_a, rev_c)
    }
    update_activity_names(generated, mapped_out, final_map)

def compare_bpmn(gold, mapped):
    comp = CompareBPMN(export_csv=False, export_excel=False)
    return comp.calculate_similarity(gold, mapped)

def process_run(args, run_idx):
    base     = os.path.splitext(os.path.basename(args.task_file))[0]
    run_name = f"{args.name}_run{run_idx}"
    print(f"\n=== Run {run_idx} for {base} ===", flush=True)

    promoai_retries = None  # <--- add this

    # 1) Generate BPMN
    try:
        if args.framework.startswith("MAO-v"):
            #suffix    = args.framework.split("MAO-v",1)[1]
            code_root = os.path.join("MAO","Code")
            gen_bpmn  = run_mao(args.task_file, args.config, args.org, run_name, args.model, code_root)
        else:
            code_root = os.path.join(
                "ProMoAI"
            )
            gen_bpmn, promoai_retries = run_promoai(args.task_file, args.model, code_root, run_name)
    except subprocess.CalledProcessError:
        print("✗ Generation failed after all retries; skipping this run.", flush=True)
        log_results(
          args.results_db, base, args.framework,
          None, None, None,
          args.gold_bpmn_filename or os.path.basename(args.gold_bpmn),
          None, args.model,
          promoai_retries="failed" if args.framework == "ProMoAI" else None
        )
        return

    print("✔ Generated BPMN:", gen_bpmn, flush=True)

    # 2) Map activity names
    mapped = args.mapped_output or gen_bpmn.replace(".bpmn", "_mapped.bpmn")
    os.makedirs(os.path.dirname(mapped), exist_ok=True)
    map_activities(gen_bpmn, args.gold_bpmn, mapped)
    print("✔ Mapped  BPMN:", mapped, flush=True)

    # 3) Compare structure
    node_sim, struct_sim, ged = compare_bpmn(args.gold_bpmn, mapped)
    print(f"→ NodeSim={node_sim:.3f}, StructSim={struct_sim:.3f}, GED={ged}", flush=True)

    # 4) Log results
    log_results(
      args.results_db, base, args.framework,
      node_sim, struct_sim, ged,
      args.gold_bpmn_filename or os.path.basename(args.gold_bpmn),
      gen_bpmn, args.model,
      promoai_retries=promoai_retries if args.framework == "ProMoAI" else None
    )

def main():
    args = parse_args()
    print(f"Pipeline → framework={args.framework}, runs={args.runs}, model={args.model}", flush=True)
    for i in range(1, args.runs + 1):
        process_run(args, i)

if __name__ == "__main__":
    main()
