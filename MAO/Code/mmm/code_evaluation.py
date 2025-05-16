# li jia hao
# 时间：2023/11/6 20:51
import os
import sys
import openai
from openai import OpenAI

client = OpenAI(api_key="sk-oEVOlF1AHtU53am90a5368Ed3b8f4597B77bEcCcF49d1c40")

sys.path.append(os.path.join(os.getcwd(),"mmm"))
directory_ChatDev = "./Warehouse/[mspaint]_DefaultOrganization_20231008195735"
# directory_MetaGPT = "./Warehouse/mspaint_THUNLP_20230821204606"#order判输，reverse判赢
directory_MetaGPT = "./Warehouse/Arcane_Arena_TaskV6_Action_Game_20231008133437"#5次均判输
# directory_MetaGPT = "./Warehouse/musicplayer_THUNLP_20230824113404"#5次中两次判平局，三次判输
# directory_MetaGPT = "./Warehouse/Enemy_Eliminator_TaskV6_Action_Game_20231009095028"#order判输，reverse判赢(发现是有源代码中包含instructionStar.py,newcode.py,删除后判输或平局，可能受代码量影响？)

def get_code(directory):
    def _format_code(code):
        code = "\n".join([line for line in code.split("\n") if len(line.strip()) > 0])
        return code

    # Read all .py files
    codebooks = {}
    assert len([filename for filename in os.listdir(directory) if filename.endswith(".py")]) > 0
    for root, directories, filenames in os.walk(directory):
        for filename in filenames:
            if filename.endswith(".py"):
                codebooks[filename] = _format_code(
                    open(os.path.join(directory, filename), "r", encoding="utf-8").read())

    # Format Codes
    code = ""
    for filename in codebooks.keys():
        code += "{}\n```Python\n{}\n```\n\n".format(filename, codebooks[filename])

    return code

code1 = get_code(directory_ChatDev)
code2 = get_code(directory_MetaGPT)

# print("code1:\n",code1)
# print("code2:\n",code2)

for root, directories, filenames in os.walk(directory_ChatDev):
    for filename in filenames:
        if filename.endswith(".prompt"):
            task = open(os.path.join(directory_ChatDev, filename), "r", encoding="utf-8").read()

print("task:",task)
#pairwise_evaluation.
def run( messages) :
    # TODO: The 'openai.api_base' option isn't read in the client API. You will need to pass it when you instantiate the client, e.g. 'OpenAI(api_base="https://sailaoda.cn/v1")'
    # openai.api_base = "https://sailaoda.cn/v1"

    response = client.chat.completions.create(messages = messages,
    model = "gpt-3.5-turbo-16k",
    temperature = 0.2,
    top_p = 1.0,
    n = 1,
    stream = False,
    frequency_penalty = 0.0,
    presence_penalty = 0.0,
    logit_bias = {})
    return response

prompt_template = """Which of the following codes complete the task better? Please choose one of the following:

task:
{task}

{code_first}:
{code1}

{code_second}:
{code2}

Your assessment should consider the following aspects:
1. Functionality Evaluation:
    1.1. Whether the code matches the task?
    1.2. Does the code implement the expected functional requirements of task?
    1.3. Whether the code can be compiled and run successfully?
    1.4. Whether there is 'pass' in the code, which means a function or part of the code is not implemented.
    1.5. Whether the functionality of the code is complete?
    1.6. Are there potential functional issues or bugs?

2. Readability Evaluation:
    2.1. Is the code easy to read and understand?
    2.2. Is the code easy to modify and maintain?

3. Coding Standards and Style Evaluation:
    3.1. Does the code conform to the coding standards?
    3.2. Does the code conform to the coding style?

4. User Experience and Interface Design Evaluation:
    4.1. Is the user interface easy to use?
    4.2. Is the user interface beautiful?
    4.3. Does it comply with user interface design principles and standards?

5. Exception handling:
    5.1. Whether the code is able to catch and handle anomalies, such as invalid input, non-existent files, network failures, etc., rather than crashing or generating errors.

Ensuring that the order in which the responses were presented does not affect your judgment!

Please output your choice between "code1" and "code2" result below:

"""

prompt_order = prompt_template.replace("{task}",task).replace("{code_first}","code1").replace("{code_second}","code2").replace("{code1}", code1).replace("{code2}", code2)
prompt_reverse = prompt_template.replace("{task}",task).replace("{code_first}","code2").replace("{code_second}","code1").replace("{code1}", code2).replace("{code2}", code1)

# print("prompt_order:\n",prompt_order)
# print("prompt_reverse:\n",prompt_reverse)

response_order = run(messages=[{"role": "system", "content": prompt_order}])["choices"][0]["message"]["content"]
response_reverse = run(messages=[{"role": "system", "content": prompt_reverse}])["choices"][0]["message"]["content"]

print("response_order:\n",response_order)
print("response_reverse:\n",response_reverse)

point1 = 0
point2 = 0

if "code1" in response_order:
    point1 += 1
elif "code2" in response_order:
    point2 += 1

if "code1" in response_reverse:
    point1 += 1
elif "code2" in response_reverse:
    point2 += 1
print("\nresult:\n")
print("Code 1: ", point1)
print("Code 2: ", point2)