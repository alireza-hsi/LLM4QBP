FROM continuumio/miniconda3:latest
WORKDIR /app

# Accept Anaconda ToS and install system deps
RUN conda config --set always_yes yes \
    && conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/main \
    && conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/r \
    && apt-get update && apt-get install -y graphviz \
    && rm -rf /var/lib/apt/lists/*

# Copy environment and requirements
COPY environment-promoai.yml environment-mao.yml ./
COPY ProMoAI/requirements.txt ProMoAI/requirements.txt
COPY MAO/requirements.txt MAO/requirements.txt

# Copy application code
COPY . .

# 1) Build the 'promoai' conda environment
RUN conda config --set always_yes yes \
    && conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/main \
    && conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/r \
    && conda env update -n promoai -f environment-promoai.yml

# 2) Build the 'MAO' conda environment and clean up
RUN conda config --set always_yes yes \
    && conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/main \
    && conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/r \
    && conda env create -f environment-mao.yml \
    && conda clean -afy

# Install vendored bpmn_python into each environment
RUN conda run -n promoai pip install -e ./libs/bpmn_python \
    && conda run -n mao pip install -e ./libs/bpmn_python

# Install Node.js for frontend tooling
RUN apt-get update && apt-get install -y curl \
    && curl -fsSL https://deb.nodesource.com/setup_18.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

EXPOSE 8501

ENV STREAMLIT_WATCHDOG_MODE=none

CMD ["streamlit", "run", "streamlit_runner.py", "--server.port=8501", "--server.enableCORS=false", "--server.runOnSave=false"]
