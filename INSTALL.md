
# Install & Run

## Prerequisites

* **Anaconda or Miniconda** installed.
* **Node.js ≥ 18** (required for BPMN auto-layout).

Initialize conda for your shell:
```
conda init <shell name>
```
(e.g., zsh, bash, PowerShell)

If your repo provides shell setup, run:

```bash
source init_path.sh
```

---

## 1) Clone the repository

```bash
git clone https://github.com/alireza-hsi/LLM4QBP.git
cd LLM4QBP
```

---

## 2) Set up Python environments

### A — MAO framework

Create and activate the MAO environment:

```bash
conda env create -f environment-mao.yml
conda activate mao
```

Install local editable Python package(s) used by MAO (e.g., `bpmn_python`):

```bash
# from repo root
pip install -e libs/bpmn_python
```

> Note: If your folder path differs, adjust accordingly.

### B — ProMoAI framework

Update your **promoai** environment from the ProMoAI spec and activate:

```bash
conda env create -f environment-promoai.yml
conda activate promoai
```

## 3) Install Node.js (for BPMN auto-layout)

Install Node.js ≥ 18 from nodejs.org (or your package manager), then verify:

```bash
node --version
npm --version
```

Install the auto-layout tool’s Node dependencies:

```bash
cd libs/bpmn_python
npm install
```

---

## 4) Run the app

From the *repo root* (with your chosen environment activated):

```bash
streamlit run streamlit_runner.py
```

---

## Quick checks / tips

* **Conda envs present?**

  ```bash
  conda env list
  ```
* **Switching environments**

  ```bash
  conda activate mao            # MAO
  conda activate promoai        # ProMoAI 
  ```
* **Streamlit installed?**

  ```bash
  python -c "import streamlit, sys; print('OK')"
  ```

  If it errors, run `pip install streamlit` in the active environment.

---

## Troubleshooting

* If `streamlit` command isn’t found, ensure you installed it **in the active environment** and that the environment is activated.
* If auto-layout fails, re-check:

  * Node.js ≥ 18 (`node --version`)
  * `npm install` was run in `MAO/Code/Helper/bpmn-auto-layout`
* On shells that don’t load conda automatically, you may need to initialize conda (e.g., `conda init bash`) or run your project’s `init_path.sh` again.


