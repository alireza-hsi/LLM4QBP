import streamlit as st
import os
import subprocess
import tempfile
import shutil
import time
import re

# Locate conda
conda_path = shutil.which("conda")
print("Using conda at:", conda_path)

PROMOAI_ENV = "promoai"
MAO_ENV = "mao"

def clear_logs():
    # Remove any previous run artifacts from session_state
    for k in list(st.session_state.keys()):
        if (
            k.startswith(("logs", "scores", "output_paths", "elapsed_time", "result_md"))
            or k.endswith(("_bytes", "_filename"))
            or k == "has_results"
        ):
            del st.session_state[k]

st.title("Process Model Pipeline Runner")

# ——— Inputs ———
api_key = st.text_input(
    "OpenAI API Key",
    type="password",
    help="Enter your OpenAI API key (it will not be displayed)."
)

framework = st.selectbox("Framework", ["ProMoAI", "MAO-v2.2", "MAO-v3", "MAO-v3.2", "MAO-v3.3", "MAO-v3.4", "MAO-v3.5", "MAO-v3.6", "MAO-v3.7", "MAO-v3.8"])
task_file = st.file_uploader("Upload task file (.txt)", type="txt")
gold_bpmn_file = st.file_uploader("Upload gold BPMN file (.bpmn, .xml) (optional)", type=["bpmn","xml"])
runs = st.number_input("Number of runs", min_value=1, value=1)
config = st.text_input("MAO config", value="Default")
org = st.text_input("MAO organization", value="DefaultOrganization")
name = st.text_input("Project name / base run name", value="PipelineRun")
model = st.text_input("Model name (e.g., GPT_4o1)", value="GPT_4o1")
mapping_model = st.text_input("Mapping model", value="gpt-4.1")
results_db = st.text_input("SQLite DB path", value="resultsDb.sqlite")

# ——— Run button with clear_logs callback ———
run = st.button("Run Pipeline", on_click=clear_logs)

# ——— Single placeholder for streaming & persisted logs ———
log_placeholder = st.empty()
if st.session_state.get("logs"):
    log_placeholder.text_area("Logs", st.session_state["logs"], height=400, disabled=True)

# ——— Pipeline execution ———
if run:
    # Validate inputs
    if not api_key:
        st.error("Please enter your OpenAI API Key.")
    elif not task_file:
        st.error("Please upload a task file.")
    else:
        # Set up env
        env = os.environ.copy()
        env["OPENAI_API_KEY"] = api_key

        # Save uploads
        tmpdir = tempfile.mkdtemp()
        task_path = os.path.join(tmpdir, task_file.name)
        with open(task_path, "wb") as f:
            f.write(task_file.read())
        gold_path = None
        if gold_bpmn_file:
            gold_path = os.path.join(tmpdir, gold_bpmn_file.name)
            with open(gold_path, "wb") as f:
                f.write(gold_bpmn_file.read())

        # Choose interpreter
        if framework.startswith("MAO-"):
            prefix = ["conda","run","-n",MAO_ENV,"python","-u"]
        else:
            prefix = ["conda","run","-n",PROMOAI_ENV,"python","-u"]

        # Build cmd
        cmd = prefix + [
            "pipeline.py",
            "--framework", framework,
            "--task-file", task_path,
            "--runs", str(runs),
            "--name", name,
            "--results-db", results_db,
            "--model", model,
            "--mapping-model", mapping_model,
        ]
        if gold_bpmn_file:
            cmd += ["--gold-bpmn", gold_path, "--gold-bpmn-filename", gold_bpmn_file.name]
        if framework.startswith("MAO-v"):
            cmd += ["--config", config, "--org", org, "--model", model]

        st.write("Running:", "`" + " ".join(cmd) + "`")

        # Run and stream
        logs = ""
        scores = None
        output_paths = {}
        start_time = time.time()
        with st.spinner("Pipeline is running..."):
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                env=env
            )
            # Stream stdout
            for line in proc.stdout:
                logs += line
                # parse scores
                if "NodeSim=" in line and "StructSim=" in line and "GED=" in line:
                    m = re.search(r"NodeSim=([0-9.]+), StructSim=([0-9.]+), GED=([0-9]+)", line)
                    if m:
                        scores = {
                            "Node Similarity": float(m.group(1)),
                            "Structure Similarity": float(m.group(2)),
                            "Graph Edit Distance": int(m.group(3))
                        }
                # parse output paths
                if "✔ Generated BPMN:" in line:
                    output_paths["Generated BPMN"] = line.split("✔ Generated BPMN:")[-1].strip()
                if "✔ Mapped  BPMN:" in line:
                    output_paths["Mapped BPMN"] = line.split("✔ Mapped  BPMN:")[-1].strip()

                # update the one and only logs area
                log_placeholder.text_area("Logs", logs, height=400, disabled=True)

            stdout, stderr = proc.communicate()
        elapsed_time = time.time() - start_time

        # show errors if any
        if stderr:
            # temp workaround
            stderr_filt = "\n".join([ line for line in stderr.split("\n") if "'MainThread': missing ScriptRunContext!" not in line ]).strip()
            
            if stderr_filt:
                st.subheader("Errors")
                st.text(stderr_filt)

        # build markdown summary
        result_md = "### ✅ Run Complete!\n\n"
        if scores:
            result_md += "**Scores:**\n"
            result_md += f"- Node Similarity: `{scores['Node Similarity']}`\n"
            result_md += f"- Structure Similarity: `{scores['Structure Similarity']}`\n"
            result_md += f"- Graph Edit Distance: `{scores['Graph Edit Distance']}`\n\n"
        if output_paths:
            result_md += "**Output Files:**\n"
            for k,v in output_paths.items():
                result_md += f"- {k}: `{v}`\n"
            result_md += "\n"
        result_md += f"**Elapsed time:** `{elapsed_time:.2f} seconds`\n\n"
        result_md += f"**Results saved in:** `{results_db}`"

        # Persist everything
        st.session_state["logs"] = logs
        st.session_state["scores"] = scores
        st.session_state["output_paths"] = output_paths
        st.session_state["elapsed_time"] = elapsed_time
        st.session_state["result_md"] = result_md
        st.session_state["has_results"] = True

        # Store any .bpmn bytes for later downloads
        for label, path in output_paths.items():
            if path.endswith(".bpmn") and os.path.exists(path):
                with open(path, "rb") as f:
                    st.session_state[f"{label}_bytes"] = f.read()
                    st.session_state[f"{label}_filename"] = os.path.basename(path)

# ——— After any run (or after download button), re‑render results/downloads ———
if st.session_state.get("has_results"):
    st.markdown(st.session_state["result_md"])
    for label in st.session_state["output_paths"]:
        bytes_key = f"{label}_bytes"
        filename_key = f"{label}_filename"
        if bytes_key in st.session_state and filename_key in st.session_state:
            st.download_button(
                label=f"Download {label}",
                data=st.session_state[bytes_key],
                file_name=st.session_state[filename_key],
                mime="application/xml",
                key=f"download_{label}"
            )
