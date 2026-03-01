import streamlit as st
import os, subprocess, tempfile, shutil, time, re, json, uuid
import sys

conda_path = shutil.which("conda")
print("Using conda at:", conda_path)

PROMOAI_ENV = "promoai"
MAO_ENV = "mao"

# Add this import at the top with other imports
sys.path.insert(0, os.path.join("MAO", "MAO(AiO version)", "Code", "Helper"))
from bpmn_compare_similarity import CompareBPMN

def clear_logs():
    for k in list(st.session_state.keys()):
        if (
            k.startswith(("logs", "scores", "output_paths", "elapsed_time", "result_md", "batch_results"))
            or k.endswith(("_bytes", "_filename"))
            or k == "has_results"
        ):
            del st.session_state[k]

def new_experiment():
    eid = uuid.uuid4().hex[:8]
    return {"id": eid}

# Add comparison function
def compare_two_bpmns(bpmn1_path, bpmn2_path):
    """Compare two BPMN files and return similarity scores."""
    comp = CompareBPMN(export_csv=False, export_excel=False)
    node_sim, struct_sim, ged = comp.calculate_similarity(bpmn1_path, bpmn2_path)
    return node_sim, struct_sim, ged

st.title("Process Model Pipeline Runner (Batch)")

# Add tabs for different modes
tab1, tab2 = st.tabs(["Batch Experiments", "BPMN Comparison"])

# ========== TAB 1: Batch Experiments (existing code) ==========
with tab1:
    api_key = st.text_input("OpenAI API Key", type="password")

    # Global defaults (used as defaults per experiment)
    default_name_prefix  = st.text_input("Default base run name", value="PipelineRun")
    default_model        = st.text_input("Default model name (e.g., GPT_5o2)", value="GPT_5o2")
    default_mapping_model= st.text_input("Default mapping model", value="gpt-5.2")
    results_db           = st.text_input("SQLite DB path", value="resultsDb.sqlite")

    max_workers = st.number_input("Parallel workers", min_value=1, value=2)

    config_options = ["Version-2.2","Version-3.0","Version-3.2","Version-3.3","Version-3.4","Version-3.5","Version-3.6","Version-3.7","Version-3.8"]

    # Init experiments list
    if "experiments" not in st.session_state:
        st.session_state["experiments"] = [new_experiment()]

    # Add button
    cols = st.columns([1, 5])
    with cols[0]:
        if st.button("➕ Add experiment"):
            st.session_state["experiments"].append(new_experiment())
            st.rerun()

    st.divider()

    # Render each experiment "card"
    for idx, exp in enumerate(st.session_state["experiments"]):
        eid = exp["id"]
        with st.expander(f"Experiment {idx+1}", expanded=True):

            top = st.columns([4, 1])
            with top[1]:
                if st.button("🗑 Remove", key=f"remove_{eid}"):
                    st.session_state["experiments"] = [e for e in st.session_state["experiments"] if e["id"] != eid]
                    st.rerun()

            # Per-experiment settings
            framework = st.selectbox(
                "Framework",
                ["ProMoAI", "MAO (AiO version)"],
                key=f"framework_{eid}"
            )

            # Runs per experiment
            runs = st.number_input("Number of runs (for this experiment)", min_value=1, value=5, key=f"runs_{eid}")

            # Optional overrides
            name_prefix = st.text_input("Run name prefix (optional override)", value=default_name_prefix, key=f"name_{eid}")
            model = st.text_input("Model (optional override)", value=default_model, key=f"model_{eid}")
            mapping_model = st.text_input("Mapping model (optional override)", value=default_mapping_model, key=f"mapping_model_{eid}")

            # Files
            task_file = st.file_uploader("Task file (.txt)", type="txt", key=f"task_{eid}")
            gold_file = st.file_uploader("Gold BPMN (optional)", type=["bpmn","xml"], key=f"gold_{eid}")

            # MAO-specific config per experiment
            mao_config = None
            mao_org = None
            if framework == "MAO (AiO version)":
                mao_config = st.selectbox("MAO Version (per experiment)", config_options, key=f"config_{eid}")
                mao_org = st.text_input("MAO organization (per experiment)", value=mao_config, key=f"org_{eid}")

    # Run button
    run_all = st.button("Run ALL Experiments", on_click=clear_logs)

    log_placeholder = st.empty()
    if st.session_state.get("logs"):
        log_placeholder.text_area("Logs", st.session_state["logs"], height=400, disabled=True)

    if run_all:
        if not api_key:
            st.error("Please enter your OpenAI API Key.")
        else:
            # Validate at least one experiment has a task file
            exps = st.session_state["experiments"]
            missing = []
            for exp in exps:
                eid = exp["id"]
                if st.session_state.get(f"task_{eid}") is None:
                    missing.append(eid)

            if len(missing) == len(exps):
                st.error("Please upload at least one task file (in at least one experiment).")
            else:
                env = os.environ.copy()
                env["OPENAI_API_KEY"] = api_key
                env["PROMOAI_ENV"] = PROMOAI_ENV
                env["MAO_ENV"] = MAO_ENV

                tmpdir = tempfile.mkdtemp()

                manifest = []
                for exp in exps:
                    eid = exp["id"]

                    tf = st.session_state.get(f"task_{eid}")
                    gf = st.session_state.get(f"gold_{eid}")

                    if tf is None:
                        continue  # skip empty card

                    fw   = st.session_state.get(f"framework_{eid}", "ProMoAI")
                    runs = int(st.session_state.get(f"runs_{eid}", 1))
                    name_prefix = st.session_state.get(f"name_{eid}", default_name_prefix)
                    model = st.session_state.get(f"model_{eid}", default_model)
                    mapping_model = st.session_state.get(f"mapping_model_{eid}", default_mapping_model)

                    config = st.session_state.get(f"config_{eid}") if fw == "MAO (AiO version)" else None
                    org    = st.session_state.get(f"org_{eid}")    if fw == "MAO (AiO version)" else None

                    # Save files (use eid prefix to avoid collisions)
                    task_path = os.path.join(tmpdir, f"{eid}__{tf.name}")
                    with open(task_path, "wb") as f:
                        f.write(tf.getvalue())

                    gold_path = None
                    gold_filename = None
                    if gf is not None:
                        gold_path = os.path.join(tmpdir, f"{eid}__{gf.name}")
                        with open(gold_path, "wb") as f:
                            f.write(gf.getvalue())
                        gold_filename = gf.name

                    manifest.append({
                        "id": eid,
                        "framework": fw,
                        "runs": runs,
                        "name": name_prefix,
                        "model": model,
                        "mapping_model": mapping_model,
                        "config": config,
                        "org": org,
                        "task_file": task_path,
                        "gold_bpmn": gold_path,
                        "gold_bpmn_filename": gold_filename
                    })

                manifest_path = os.path.join(tmpdir, "batch_manifest.json")
                with open(manifest_path, "w", encoding="utf-8") as f:
                    json.dump(manifest, f, indent=2)

                # IMPORTANT: In mixed framework batches, don't conda-run pipeline itself.
                # Let pipeline spawn the correct env per job.
                cmd = [
                    "python", "-u", "pipeline.py",
                    "--batch-manifest", manifest_path,
                    "--max-workers", str(int(max_workers)),
                    "--results-db", results_db,
                ]

                st.write("Running:", "`" + " ".join(cmd) + "`")

                logs = ""
                start_time = time.time()

                with st.spinner("Batch is running..."):
                    proc = subprocess.Popen(
                        cmd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        bufsize=1,
                        env=env
                    )
                    progress_bar = st.progress(0.0)
                    progress_text = st.empty()

                    for line in proc.stdout:
                        logs += line
                        log_placeholder.text_area("Logs", logs, height=400, disabled=True)

                        m = re.search(r"PROGRESS (\d+)/(\d+)", line)
                        if m:
                            done = int(m.group(1))
                            total = int(m.group(2))
                            progress_bar.progress(done / total)
                            progress_text.write(f"{done}/{total} runs complete")

                    stdout, stderr = proc.communicate()

                elapsed_time = time.time() - start_time

                if stderr:
                    stderr_filt = "\n".join(
                        [ln for ln in stderr.split("\n") if "'MainThread': missing ScriptRunContext!" not in ln]
                    ).strip()
                    if stderr_filt:
                        st.subheader("Errors")
                        st.text(stderr_filt)

                st.session_state["logs"] = logs
                st.session_state["elapsed_time"] = elapsed_time
                st.session_state["has_results"] = True
                st.success(f"Done in {elapsed_time:.2f}s. Results saved in {results_db}.")

# ========== TAB 2: BPMN Comparison ==========
with tab2:
    st.header("Compare Two BPMN Files")
    st.markdown("Upload two BPMN files to compare their similarity scores.")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("First BPMN File")
        bpmn1_file = st.file_uploader("Upload first BPMN", type=["bpmn", "xml"], key="bpmn1")
        if bpmn1_file:
            st.info(f"📄 {bpmn1_file.name}")
    
    with col2:
        st.subheader("Second BPMN File")
        bpmn2_file = st.file_uploader("Upload second BPMN", type=["bpmn", "xml"], key="bpmn2")
        if bpmn2_file:
            st.info(f"📄 {bpmn2_file.name}")
    
    compare_button = st.button("🔍 Compare BPMN Files", type="primary")
    
    if compare_button:
        if not bpmn1_file or not bpmn2_file:
            st.error("Please upload both BPMN files to compare.")
        else:
            with st.spinner("Comparing BPMN files..."):
                # Save uploaded files temporarily
                tmpdir = tempfile.mkdtemp()
                try:
                    bpmn1_path = os.path.join(tmpdir, bpmn1_file.name)
                    bpmn2_path = os.path.join(tmpdir, bpmn2_file.name)
                    
                    with open(bpmn1_path, "wb") as f:
                        f.write(bpmn1_file.getvalue())
                    with open(bpmn2_path, "wb") as f:
                        f.write(bpmn2_file.getvalue())
                    
                    # Compare
                    node_sim, struct_sim, ged = compare_two_bpmns(bpmn1_path, bpmn2_path)
                    
                    # Display results
                    st.success("Comparison complete!")
                    st.divider()
                    
                    # Results in columns
                    st.subheader("Similarity Scores")
                    col1, col2, col3 = st.columns(3)
                    
                    with col1:
                        st.metric("Node Similarity", f"{node_sim:.3f}")
                    with col2:
                        st.metric("Structure Similarity", f"{struct_sim:.3f}")
                    with col3:
                        st.metric("Graph Edit Distance", f"{ged}")
                    
                    # Detailed results
                    with st.expander("📊 Detailed Results"):
                        st.write(f"**Node Similarity:** {node_sim:.4f}")
                        st.write(f"**Structure Similarity:** {struct_sim:.4f}")
                        st.write(f"**Graph Edit Distance:** {ged}")
                        st.write(f"\n**File 1:** {bpmn1_file.name}")
                        st.write(f"**File 2:** {bpmn2_file.name}")
                    
                except Exception as e:
                    st.error(f"Error during comparison: {str(e)}")
                    st.exception(e)
                finally:
                    # Cleanup temp files
                    shutil.rmtree(tmpdir, ignore_errors=True)