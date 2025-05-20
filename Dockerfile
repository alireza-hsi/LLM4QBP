FROM continuumio/miniconda3:latest
WORKDIR /app

RUN apt-get update && apt-get install -y graphviz && rm -rf /var/lib/apt/lists/*

# Copy environment and requirements files first (for cache efficiency)
COPY environment-base.yml environment-mao.yml ./
COPY ProMoAI/requirements.txt ProMoAI/requirements.txt
COPY MAO/Code/requirements.txt MAO/Code/requirements.txt

# Copy the entire codebase (including libs/bpmn_python)
COPY . .

# Build both conda envs
RUN conda env update -n base -f environment-base.yml \
 && conda env create -f environment-mao.yml \
 && conda clean -afy

# Install your vendored bpmn_python into each env
RUN conda run -n base pip install -e ./libs/bpmn_python \
 && conda run -n MAO_conda_env pip install -e ./libs/bpmn_python

# Test the install (optional, but recommended for debugging)
RUN conda run -n base python -c "import bpmn_python"

EXPOSE 8501

CMD ["streamlit", "run", "streamlit_runner.py", "--server.port=8501", "--server.enableCORS=false"]