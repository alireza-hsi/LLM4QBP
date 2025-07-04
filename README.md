# LLM4QBP
Repository for the paper LLM4QBP which contains codes, prompt, experiment results, etc.

---

## 🚀 Live Demo

You can try the pipeline instantly online:

- **Main Web UI:** [http://notation3.org:8501/](http://notation3.org:8501/)
- **Results Dashboard:** [http://notation3.org:8502/](http://notation3.org:8502/)

**NOTE**: these links may be inaccessible based on the firewall settings of your network. 
In that case (e.g., connection timeout), you can try setting up the pipeline yourself.

---


This repository provides a unified pipeline for generating, mapping, and evaluating BPMN process models using two frameworks:
- **MAO**
- **ProMoAI**

It supports activity mapping, BPMN similarity comparison, and experiment result logging, and is designed for reproducible, multi-run experiments.

## Quick Start

Welcome to **LLM4QBP**!  
You can use all features of this project instantly with our prebuilt Docker image—**no build or setup required**.

---

## Quick Start: Use the Prebuilt Docker Image

### 1. **Pull the Latest Image**
```sh
docker pull alirezahsi/llm4qbp:latest
```

### 2. **Run the Streamlit Web UI**
This launches the main web interface for running the pipeline:
```sh
docker run --rm -p 8501:8501 -v $(pwd):/app alirezahsi/llm4qbp:latest streamlit run streamlit_runner.py
```
- Open [http://localhost:8501](http://localhost:8501) in your browser.
- The `-v $(pwd):/app` option mounts your current directory into the container, so you can access your files and save outputs.

### 3. **Run the Dashboard (Results Visualization)**
To launch the interactive dashboard for exploring results:
```sh
docker run --rm -p 8501:8501 -v $(pwd):/app alirezahsi/llm4qbp:latest streamlit run dashboard.py
```
- Open [http://localhost:8501](http://localhost:8501) in your browser.
- The dashboard reads your results database (e.g., `resultsDb.sqlite`) and provides interactive tables and plots.

### 4. **Run the Pipeline or Any Script from the Command Line**
You can run any script inside the container, for example:
```sh
docker run --rm -v $(pwd):/app alirezahsi/llm4qbp:latest python pipeline.py <args>
```
Replace `<args>` with your desired command-line arguments.

---

## 📝 Notes

- **No build required:** You do **not** need to build the Docker image yourself. Just pull and run!
- **File access:** All outputs and logs will appear in your current directory, thanks to the `-v $(pwd):/app` volume mount.
- **Multiple apps:** You can run the web UI and dashboard separately (but not on the same port at the same time).

---

## Example: Running Both Web UI and Dashboard

To run both at once, use different ports:
```sh
# Web UI on port 8501
docker run --rm -p 8501:8501 -v $(pwd):/app alirezahsi/llm4qbp:latest streamlit run streamlit_runner.py

# Dashboard on port 8502
docker run --rm -p 8502:8501 -v $(pwd):/app alirezahsi/llm4qbp:latest streamlit run dashboard.py --server.port=8501
```
Then visit [http://localhost:8501](http://localhost:8501) for the web UI and [http://localhost:8502](http://localhost:8502) for the dashboard.

---

## Example Files for Quick Testing

After cloning the repository, you can use these example files to quickly test the Streamlit UI:

- [`QBPs/QBP_1/QBP_1_cleaned.txt`](./QBPs/QBP_1/QBP_1_cleaned.txt) — Example QBP task file
- [`QBPs/QBP_1/QBP1_v2.bpmn`](./QBPs/QBP_1/QBP1_v2.bpmn) — Example gold-standard BPMN file

**How to use:**
1. In the Streamlit UI, upload `QBPs/QBP_1/QBP_1_cleaned.txt` as the task file and `QBPs/QBP_1/QBP1_v2.bpmn` as the gold BPMN file.
2. Click "Run Pipeline" to see the results.

## Troubleshooting

- **FileNotFoundError:**  
  Ensure your input files are in the current directory and you use the correct paths.
- **Permission issues:**  
  If you get permission errors, try running with your user ID:
  ```sh
  docker run --rm -u $(id -u):$(id -g) -v $(pwd):/app ...
  ```

---

### (Alternative) Run Locally with Conda

- **Explore LLM-generated QBP and Prompt Samples:**  
  Find random QBP (Question-Based Process) samples and prompt examples generated by LLMs in the [`LLM-generated QBP and Prompt Examples`](./LLM-generated%20QBP%20and%20Prompt%20Examples) folder.  
  - Each sample comes with its corresponding `.svg` file for easy visualization.
  - Subfolders are organized by framework (`MAO`, `ProMoAI`) and QBP number.

- **Database of Experiment Runs:**  
  All experiment runs are logged in a detailed SQLite database (default: `resultsDb.sqlite`).  
  - Each row contains information about a single run, including parameters, similarity scores, and file paths.
  - Use the `generated_bpmn_path` column to locate the exact `.bpmn` file generated for any run.

- **Find Your Outputs and Logs:**  
  - All generated BPMN files and run logs are saved in their corresponding subfolders under the `WareHouse` directory of each framework:
    - For MAO: `MAO/Code/WareHouse/`
    - For ProMoAI: `ProMoAI/WareHouse/`
  - Each run gets its own timestamped folder containing the BPMN file and logs.

- **Try It Yourself – Recommended: Streamlit Web UI!**  
  The easiest way to run your own experiments is with our Streamlit web interface.  
  **To launch the web UI, simply run:**
  ```sh
  streamlit run streamlit_runner.py
  ```
  - This will open a browser window where you can upload your QBP task and gold BPMN files, select parameters, and run the pipeline interactively.
  - Results and logs will be saved just as in the command-line version.

- **Ready to Run from the Command Line?**  
  - See the [Usage](#usage) section below for command-line instructions.


---

## Directory Structure

```
├── pipeline.py # Main pipeline script for running experiments
├── streamlit_runner.py # Streamlit web UI for running the pipeline
├── dashboard.py # Dashboard for results visualization
├── dbModifier.py # Utility script for modifying the results database
├── resultsDb.sqlite # Example SQLite results database
├── 15_runs_results.sqlite # Another example results database
├── LLM-generated QBP and Prompt Examples/
│ ├── MAO/
│ │ ├── QBP 1/
│ │ ├── QBP 2/
│ │ ├── QBP 3/
│ │ └── QBP 4/
│ └── ProMoAI/
│ ├── QBP1/
│ ├── QBP2/
│ ├── QBP3/
│ ├── QBP4/
│ └── Prompt example.txt
├── ProMoAI/
│ ├── ProMoAI_API.py
│ ├── WareHouse/ # ProMoAI output BPMN files and logs (per run)
│ ├── QBP_1/ ... QBP_4/ # QBP-specific folders
│ └── ...
├── MAO/
│ └── Code/
│ ├── run.py
│ ├── Helper/
│ ├── WareHouse/ # MAO output BPMN files and logs (per run)
│ └── ...
├── QBPs/ # Example QBP input files
├── WareHouse/ # (Legacy/unused) Top-level output directory
└── README.md
```

---

## Requirements

- Python 3.8+
- [Anaconda/Miniconda](https://docs.conda.io/en/latest/)
- The following conda environments:
  - `base` (for ProMoAI)
  - `MAO_conda_env` (for MAO)
- All dependencies listed in `MAO/Code/requirements.txt` and `ProMoAI/requirements.txt` 

---

## Usage

### 1. **Command-Line Pipeline**

Run the pipeline for either framework:

```sh
# For ProMoAI
conda run -n base python pipeline.py \
  --framework ProMoAI \
  --task-file <input_task.txt> \
  --gold-bpmn <gold.bpmn> \
  --runs 3 \
  --name MyExperiment \
  --results-db my_results.sqlite \
  --model GPT_4o1

# For MAO
conda run -n MAO_conda_env python pipeline.py \
  --framework MAO-v2.2 \
  --task-file <input_task.txt> \
  --gold-bpmn <gold.bpmn> \
  --runs 3 \
  --name MyExperiment \
  --results-db my_results.sqlite \
  --model GPT_4o1 \
  --config Default \
  --org DefaultOrganization
```

### 2. **Streamlit Web UI for Running the Pipeline**

Launch the web interface to run experiments:

```sh
streamlit run streamlit_runner.py
```

- Upload your task and gold BPMN files, select parameters, and run the pipeline interactively.

### 3. **Streamlit Dashboard for Results Visualization**

Visualize and analyze your experiment results with the dashboard:

```sh
streamlit run dashboard.py
```

- This app reads your results database (e.g., `resultsDb.sqlite`) and provides interactive tables and plots for:
  - Node/structure similarity
  - Graph edit distance
  - Framework/model comparisons
  - Filtering and exploring individual runs

## Output

- **Generated BPMN files** are saved in:
  - `ProMoAI/WareHouse/` (for ProMoAI)
  - `MAO/Code/WareHouse/` (for MAO)
- **Experiment results** are logged in the specified SQLite database (default: `resultsDb.sqlite`).

Each run logs:
- Timestamps
- QBP/task name
- Framework and model used
- Node and structure similarity
- Graph edit distance
- Paths to gold and generated BPMN files
- Retry info (for ProMoAI)

---

## Customization

- **Directory Structure:**  
  The pipeline expects the output directories to match the structure above. If you change the structure, update the path handling in `pipeline.py`.

---

## Troubleshooting

- **FileNotFoundError:**  
  Ensure the generated BPMN file paths are correct and that the pipeline is using the full path, not just a relative one.
- **Conda Environment Issues:**  
  Make sure you have the correct environments and dependencies installed.

---

## License



---

## Acknowledgements

- MAO and ProMoAI frameworks
- OpenAI GPT models and APIs
- This project uses [bpmn-auto-layout](https://github.com/bpmn-io/bpmn-auto-layout) for automatic BPMN diagram layout.


---

**For questions or contributions, please open an issue or pull request.**


