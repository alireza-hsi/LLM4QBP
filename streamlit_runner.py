import streamlit as st
import sys
import subprocess
import os
import tempfile
import shutil
import time

# Locate conda
conda_path = shutil.which("conda")
print("Using conda at:", conda_path)

# Streamlit UI
st.title("Process Model Pipeline Runner")

# let the user enter their OpenAI key ————————————————
api_key = st.text_input(
    "OpenAI API Key",
    type="password",
    help="Enter your OpenAI API key (it will not be displayed)."
)

framework = st.selectbox(
    "Framework",
    ["ProMoAI", "MAO-v2.2"]
)

task_file = st.file_uploader(
    "Upload task file (.txt)",
    type="txt"
)
gold_bpmn_file = st.file_uploader(
    "Upload gold BPMN file (.bpmn, .xml)",
    type=["bpmn", "xml"]
)

runs = st.number_input(
    "Number of runs",
    min_value=1,
    value=1
)

config = st.text_input(
    "MAO config",
    value="Default"
)
org = st.text_input(
    "MAO organization",
    value="DefaultOrganization"
)

name = st.text_input(
    "Project name / base run name",
    value="PipelineRun"
)

model = st.text_input(
    "Model name (e.g., GPT_4o1)",
    value="GPT_4o1",
    help="Which GPT model to use for the process generation step. 4o1 is 4.1 here."
)

mapping_model = st.text_input(
    "Mapping model",
    value="gpt-4.1",
    help="Which GPT model to use for the activity-mapping step"
)

results_db = st.text_input(
    "SQLite DB path",
    value="resultsDb.sqlite"
)

CONDA_ENV = "MAO_conda_env"

if st.button("Run Pipeline"):
    # Validate inputs
    if not api_key:
        st.error("Please enter your OpenAI API Key.")
    elif not task_file or not gold_bpmn_file:
        st.error("Please upload both a task file and a gold BPMN file.")
    else:
        # Prepare environment with API key for subprocess
        env = os.environ.copy()
        env["OPENAI_API_KEY"] = api_key

        # Save uploaded files to a temp directory
        tmpdir = tempfile.mkdtemp()
        task_path = os.path.join(tmpdir, task_file.name)
        with open(task_path, "wb") as f:
            f.write(task_file.read())
        gold_path = os.path.join(tmpdir, gold_bpmn_file.name)
        with open(gold_path, "wb") as f:
            f.write(gold_bpmn_file.read())

        # Choose the right Python interpreter based on framework
        if framework.startswith("MAO-"):
            prefix = ["conda", "run", "-n", CONDA_ENV, "python", "-u"]
        else:
            prefix = ["conda", "run", "-n", "base", "python", "-u"]

        # Build the command
        cmd = prefix + [
            "pipeline.py",
            "--framework", framework,
            "--task-file", task_path,
            "--gold-bpmn", gold_path,
            "--runs", str(runs),
            "--name", name,
            "--results-db", results_db,
            "--model", model,
            "--mapping-model", mapping_model,
            "--gold-bpmn-filename", gold_bpmn_file.name
        ]

        if framework.startswith("MAO-v"):
            cmd += [
                "--config", config,
                "--org", org,
                "--model", model
            ]

        st.write("Running: `%s`" % " ".join(cmd))

        # Real-time log streaming
        log_placeholder = st.empty()
        error_placeholder = st.empty()
        result_placeholder = st.empty()
        logs = ""
        scores = None
        output_paths = {}
        elapsed_time = None

        with st.spinner("Pipeline is running..."):
            start_time = time.time()
            with subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                env=env
            ) as process:
                for line in process.stdout:
                    logs += line
                    # Try to parse scores and output paths from the log lines
                    if "NodeSim=" in line and "StructSim=" in line and "GED=" in line:
                        import re
                        m = re.search(r"NodeSim=([0-9.]+), StructSim=([0-9.]+), GED=([0-9]+)", line)
                        if m:
                            scores = {
                                "Node Similarity": float(m.group(1)),
                                "Structure Similarity": float(m.group(2)),
                                "Graph Edit Distance": int(m.group(3))
                            }
                    if "✔ Generated BPMN:" in line:
                        output_paths["Generated BPMN"] = line.split("✔ Generated BPMN:")[-1].strip()
                    if "✔ Mapped  BPMN:" in line:
                        output_paths["Mapped BPMN"] = line.split("✔ Mapped  BPMN:")[-1].strip()
                    log_placeholder.text_area("Logs", logs, height=400, disabled=True)
                process.wait()
                errors = process.stderr.read()
                if errors:
                    error_placeholder.subheader("Errors")
                    error_placeholder.text(errors)
            elapsed_time = time.time() - start_time

        # Show results in a user-friendly format
        if scores or output_paths:
            result_md = "### ✅ Run Complete!\n"
            if scores:
                result_md += "**Scores:**\n"
                result_md += f"- Node Similarity: `{scores['Node Similarity']}`\n"
                result_md += f"- Structure Similarity: `{scores['Structure Similarity']}`\n"
                result_md += f"- Graph Edit Distance: `{scores['Graph Edit Distance']}`\n"
            if output_paths:
                result_md += "\n**Output Files:**\n"
                for k, v in output_paths.items():
                    result_md += f"- {k}: `{v}`\n"
            if elapsed_time is not None:
                result_md += f"\n**Elapsed time:** `{elapsed_time:.2f} seconds`"
            result_md += f"\n\n**Results saved in:** `{results_db}`"
            result_placeholder.markdown(result_md)
