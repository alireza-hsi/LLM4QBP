# pipeline.py
# ── Monkey-patch for bpmn_python compatibility with NetworkX 2.x ─────────────
#import networkx as nx
#if not hasattr(nx.Graph, 'node'):
    # .node was a dict of node attributes in NX1.x, now use .nodes in NX2.x
#    nx.Graph.node = property(lambda self: self.nodes)
#if not hasattr(nx.Graph, 'edge'):
    # .node was a dict of node attributes in NX1.x, now use .nodes in NX2.x
#    nx.Graph.edge = property(lambda self: self.edges)
# ───────────────────────────────────────────────────────────────────────────────


# pipeline.py: Orchestrates MAO generation, activity mapping, and BPMN comparison
import argparse
import os
import subprocess
import sys
import sqlite3
# Ensure helper folder is on path
root = os.path.dirname(__file__)
sys.path.append(os.path.join(root, "helper"))

from automatedActivityMapping import (
    extract_activity_names,
    get_alignment,
    get_revision,
    update_activity_names
)
from bpmn_compare_similarity import CompareBPMN


def log_results_sqlite(db_path, qbp_name, mao_version, node_sim, struct_sim, ged):
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS experiment_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            qbp_name TEXT,
            mao_version TEXT,
            node_similarity REAL,
            structure_similarity REAL,
            graph_edit_distance INTEGER
        )
    ''')
    c.execute('''
        INSERT INTO experiment_results (timestamp, qbp_name, mao_version, node_similarity, structure_similarity, graph_edit_distance)
        VALUES (datetime('now'), ?, ?, ?, ?, ?)
    ''', (qbp_name, mao_version, node_sim, struct_sim, ged))
    conn.commit()
    conn.close()

def run_mao(task_file, config, org, name, model):
    """
    Runs the MAO tool (run.py) to generate a BPMN file.
    Returns the path to the generated BPMN file.
    """
    cmd = [
        sys.executable, os.path.join(root, "run.py"),
        "--task-file", task_file,
        "--config", config,
        "--org", org,
        "--name", name,
        "--model", model
    ]
    subprocess.run(cmd, check=True)
    # MAO outputs into WareHouse/{name}_{org}_*/process.bpmn (for example)
    # Adjust this pattern to match your run.py output behavior
    base_dir = os.path.join(root, "WareHouse")
    # find the most recent project folder
    project_dirs = sorted(
        [d for d in os.listdir(base_dir) if d.startswith(name + "_") and org in d],
        key=lambda d: os.path.getmtime(os.path.join(base_dir, d)),
        reverse=True
    )
    if not project_dirs:
        raise FileNotFoundError("Could not find MAO output directory in WareHouse.")
    project_path = os.path.join(base_dir, project_dirs[0])
    # assume output file is named "process.bpmn"
    output_bpmn = os.path.join(project_path, "process.bpmn")
    if not os.path.exists(output_bpmn):
        raise FileNotFoundError(f"Expected BPMN file not found at {output_bpmn}")
    return output_bpmn


def map_activities(generated_bpmn, gold_bpmn, mapped_bpmn):
    """
    Uses automatedActivityMapping to align activities and write a mapped BPMN file.
    """
    set_a = extract_activity_names(generated_bpmn)
    set_b = extract_activity_names(gold_bpmn)
    mapping, set_c, full_table = get_alignment(set_a, set_b)
    revised = get_revision(set_a, set_b, full_table)
    namespace = {}
    exec(revised, {}, namespace)
    rev_set_a = namespace.get('Set_A', set_a)
    rev_set_c = namespace.get('Set_C', set_c)
    final_mapping = {}
    for a, c in zip(rev_set_a, rev_set_c):
        final_mapping[a] = a if c.strip().lower().startswith("no match") else c
    update_activity_names(generated_bpmn, mapped_bpmn, final_mapping)
    return mapped_bpmn


def compare_bpmn(gold_bpmn, mapped_bpmn):
    """
    Compares two BPMN files and prints similarity scores.
    """
    comparator = CompareBPMN(export_csv=False, export_excel=False)
    node_sim, struct_sim, ged = comparator.calculate_similarity(gold_bpmn, mapped_bpmn)
    return node_sim, struct_sim, ged


def main():
    parser = argparse.ArgumentParser(description="Pipeline: MAO -> Mapping -> Comparison")
    parser.add_argument("--task-file", required=True, help="Path to .txt file with task description")
    parser.add_argument("--gold-bpmn", required=True, help="Path to gold-standard BPMN file")
    parser.add_argument("--config", default="Default", help="MAO config folder name")
    parser.add_argument("--org", default="DefaultOrganization", help="Organization name for MAO output")
    parser.add_argument("--name", default="PipelineProject", help="Project name for MAO output")
    parser.add_argument("--model", default="GPT_4o1", help="GPT model to use in MAO (e.g. GPT_4)")
    parser.add_argument("--mapped-output", default=None, help="Path for mapped BPMN output (optional)")
    parser.add_argument("--mao-version", default="2.2", help="MAO version for logging")
    parser.add_argument(
        "--results-db",
        default="/Users/alireza/Desktop/DTI/Thesis/code experiments/experiment_results.sqlite",
        help="SQLite DB file to log results"
    )
    args = parser.parse_args()

    # Step 1: Generate BPMN via MAO
    print("[1/3] Generating BPMN with MAO...")
    gen_bpmn = run_mao(args.task_file, args.config, args.org, args.name, args.model)
    print(f"Generated BPMN: {gen_bpmn}")

    # Step 2: Activity mapping
    mapped_path = args.mapped_output or os.path.splitext(gen_bpmn)[0] + "_mapped.bpmn"
    print("[2/3] Mapping activities...")
    map_activities(gen_bpmn, args.gold_bpmn, mapped_path)
    print(f"Mapped BPMN saved to: {mapped_path}")

    # Step 3: Comparison
    print("[3/3] Comparing BPMNs...")
    node_sim, struct_sim, ged = compare_bpmn(args.gold_bpmn, mapped_path)
    print("===================================")
    print("      BPMN Similarity Results      ")
    print("===================================")
    print(f"Gold vs. Mapped:")
    print(f"- Node Similarity:       {node_sim:.3f}")
    print(f"- Structure Similarity:  {struct_sim:.3f}")
    print(f"- Graph Edit Distance:   {ged}")
    print("===================================")

    # Save results to SQLite
    qbp_name = os.path.splitext(os.path.basename(args.task_file))[0]
    mao_version = args.mao_version
    db_path = args.results_db
    log_results_sqlite(db_path, qbp_name, mao_version, node_sim, struct_sim, ged)
    print(f"Results saved to {db_path}")

if __name__ == "__main__":
    main()
