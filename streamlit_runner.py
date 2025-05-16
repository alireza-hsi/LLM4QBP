import streamlit as st
import sys
import subprocess
import os
import tempfile
import shutil

conda_path = shutil.which("conda")
print("Using conda at:", conda_path)

st.title("Process Model Pipeline Runner")

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
    value="GPT_4o1"
)

results_db = st.text_input(
    "SQLite DB path",
    value="15_runs_results.sqlite"
)

CONDA_ENV = "MAO_conda_env"

if st.button("Run Pipeline"):
    if not task_file or not gold_bpmn_file:
        st.error("Please upload both a task file and a gold BPMN file.")
    else:
        tmpdir = tempfile.mkdtemp()
        task_path = os.path.join(tmpdir, task_file.name)
        with open(task_path, "wb") as f:
            f.write(task_file.read())
        gold_path = os.path.join(tmpdir, gold_bpmn_file.name)
        with open(gold_path, "wb") as f:
            f.write(gold_bpmn_file.read())

        # pick the right Python interpreter
        if framework.startswith("MAO-"):
            prefix = ["conda", "run", "-n", "MAO_conda_env", "python", "-u"]
        else:
            prefix = ["conda", "run", "-n", "base", "python", "-u"]

        cmd = prefix + [
            "pipeline.py",
            "--framework",  framework,
            "--task-file",  task_path,
            "--gold-bpmn",  gold_path,
            "--runs",       str(runs),
            "--name",       name,
            "--results-db", results_db,
            "--model",      model,
            "--gold-bpmn-filename", gold_bpmn_file.name
        ]
        
        if framework.startswith("MAO-v"):
            cmd += [
                '--config', config,
                '--org', org,
                '--model', model
            ]
        else:
            cmd += ['--model', model]

        st.write("Running: %s" % ' '.join(cmd))

        # Real-time log streaming
        log_placeholder = st.empty()
        error_placeholder = st.empty()
        with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1) as process:
            logs = ""
            for line in process.stdout:
                logs += line
                log_placeholder.text(logs)
            process.wait()
            # Show any errors
            errors = process.stderr.read()
            if errors:
                error_placeholder.subheader("Errors")
                error_placeholder.text(errors)

