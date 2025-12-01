### 🖥️ Quickstart with terminal

To get started, follow these steps:

1. **Clone the GitHub Repository** 

2. **Set Up Python Environment:** Ensure you have a version 3.9 or higher Python environment. You can create and
   activate this environment using the following commands, replacing `MAO_conda_env` with your preferred environment
   name:

   ```
   conda create -n MAO_conda_env python=3.9 -y
   conda activate MAO_conda_env
   ```

3. **Install Dependencies:** Move into the `MAO` directory and install the necessary dependencies by running:

   ```
   cd MAO
   pip3 install -r requirements.txt
   ```

4. **Set OpenAI API Key:** Export your OpenAI API key as an environment variable. Replace `"your_OpenAI_API_key"` with
   your actual API key. Remember that this environment variable is session-specific, so you need to set it again if you
   open a new terminal session.
   On Unix/Linux:

   ```
   export OPENAI_API_KEY=""
   ```

   On Windows:

   ```
   $env:OPENAI_API_KEY="your_OpenAI_API_key"
   ```

5. **Build Your Process:** Use the following command to initiate the building of your process,
   replacing `[your rask]` with your task and `[project_name]` with your desired project
   name:
   On Unix/Linux:

   ```
   python3 run.py --task "[your task]" --name "[project_name]"
   ```

   On Windows:

   ```
   python run.py --task "[your task]" --name "[project_name]"
   ```


