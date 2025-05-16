# LLM4QBP
Repository for the paper LLM4QBP which contains codes, prompt, experiment results, etc.


This repository provides a unified pipeline for generating, mapping, and evaluating BPMN process models using two frameworks:
- **MAO-v2.2**
- **ProMoAI**

It supports activity mapping, BPMN similarity comparison, and experiment result logging, and is designed for reproducible, multi-run experiments.

---

## Directory Structure

```
.
├── pipeline.py                # Main pipeline script for running experiments
├── streamlit_runner.py        # Streamlit web UI for running the pipeline
├── dashboard.py               # (Optional) Dashboard for results visualization
├── db_modifications.py        # Utility scripts for modifying the results database
├── 15_runs_results.sqlite     # Example SQLite results database
├── Test_4_ProMoAI_API_BPMN/   # ProMoAI code and output directory
│   ├── test4.py               # ProMoAI main script
│   └── WareHouse/             # ProMoAI output BPMN files
├── Version-2.2/               # MAO-v2.2 code and output directory
│   └── Code/
│       ├── run.py             # MAO main script
│       ├── Helper/            # MAO helper modules
│       └── WareHouse/         # MAO output BPMN files
├── QBPs/                      # (Optional) Example QBP input files
├── WareHouse/                 # (Legacy/unused) Top-level output directory
└── README.md                  # This file
```

---

## Requirements

- Python 3.8+
- [Anaconda/Miniconda](https://docs.conda.io/en/latest/)
- The following conda environments:
  - `base` (for ProMoAI)
  - `MAO_conda_env` (for MAO-v2.2)
- All dependencies listed in `Version-2.2/Code/requirements.txt` and `Test_4_ProMoAI_API_BPMN/requirements.txt` (if present)

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

# For MAO-v2.2
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

- This app reads your results database (e.g., `15_runs_results.sqlite`) and provides interactive tables and plots for:
  - Node/structure similarity
  - Graph edit distance
  - Framework/model comparisons
  - Filtering and exploring individual runs

## Output

- **Generated BPMN files** are saved in:
  - `Test_4_ProMoAI_API_BPMN/WareHouse/` (for ProMoAI)
  - `Version-2.2/Code/WareHouse/` (for MAO-v2.2)
- **Experiment results** are logged in the specified SQLite database (default: `15_runs_results.sqlite`).

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
- OpenAI GPT models for analytics

---

**For questions or contributions, please open an issue or pull request.**


