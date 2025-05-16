# li jia hao
# 时间：2023/11/7 21:23
import os
import re
import sys
import difflib
from utils import get_easyDict_from_filepath


sys.path.append(os.path.join(os.getcwd(),"mmm"))
cfg = get_easyDict_from_filepath("./mmm/config.yaml")

directory = "./Warehouse/Background_Blur_Editor_TaskV6_Photo_20230927010619"
# directory = "./Warehouse/Animation_Creator_TaskV6_Graphics_20230926171153"

def update_codebook(utterance, codebook):
    def extract_filename_from_line(lines):
        file_name = ""
        for candidate in re.finditer(r"(\w+\.\w+)", lines, re.DOTALL):
            file_name = candidate.group()
            file_name = file_name.lower()
        return file_name

    def extract_filename_from_code(code):
        file_name = ""
        regex_extract = r"class (\S+?):\n"
        matches_extract = re.finditer(regex_extract, code, re.DOTALL)
        for match_extract in matches_extract:
            file_name = match_extract.group(1)
        file_name = file_name.lower().split("(")[0] + ".py"
        return file_name

    def _format_code(code):
        code = "\n".join([line for line in code.split("\n") if len(line.strip()) > 0])
        return code

    regex = r"(.+?)\n```.*?\n(.*?)```"
    matches = re.finditer(regex, utterance, re.DOTALL)
    for match in matches:
        code = match.group(2)
        if "CODE" in code:
            continue
        group1 = match.group(1)
        filename = extract_filename_from_line(group1)
        if "__main__" in code:
            filename = "main.py"
        if filename == "":
            filename = extract_filename_from_code(code)
        assert filename != ""
        if filename is not None and code is not None and len(filename) > 0 and len(code) > 0:
            codebook[filename] = _format_code(code)

def get_codes(codebook):
    content = ""
    for filename in codebook.keys():
        content += "{}\n```{}\n{}\n```\n\n".format(filename, "python" if filename.endswith(".py") else
        filename.split(".")[-1], codebook[filename])
    return content

directory = directory
logdir = [filename for filename in os.listdir(directory) if filename.endswith(".log")]
if len(logdir) > 0:
    log_filename = logdir[0]
    print("log_filename:", log_filename)
else:
    raise Exception("No log file found in {}".format(directory))

content = open(os.path.join(directory, log_filename), "r", encoding='UTF-8').read()

utterances = []
regex = r"\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} \w+)\] ([.\s\S\n\r\d\D\t]*?)(?=\n\[\d|$)"
matches = re.finditer(regex, content, re.DOTALL)
for match in matches:
    group1 = match.group(1)
    group2 = match.group(2)
    utterances.append("[{}] {}".format(group1, group2))
utterances = [utterance for utterance in utterances if
              "flask app.py" not in utterance and "OpenAI_Usage_Info" not in utterance]
index = [i for i, utterance in enumerate(utterances) if
         "Programmer<->Chief Technology Officer on : EnvironmentDoc" in utterance]
utterances = utterances[:index[0] - 1]

diffindex = [i for i, utterance in enumerate(utterances) if
             "Code Reviewer<->Programmer on : CodeReviewComment" in utterance]

utterances_diff = utterances[diffindex[0] - 2:]

utterances_code = [utterance for utterance in utterances_diff if
                   "Programmer<->" in utterance and "EnvironmentDoc" not in utterance and "TestErrorSummary" not in utterance]


utterances_comment = [utterance for utterance in utterances if
                      "Code Reviewer: **[Start Chat]**" in utterance and "EnvironmentDoc" not in utterance and "TestErrorSummary" not in utterance]


codebook, fingerprints = {}, set()
codelist = []
commentlist = []
difflist = []

for utterance in utterances_code:
    update_codebook(utterance, codebook)
    code = get_codes(codebook)
    codelist.append(code)

for utterance in utterances_comment:
    pattern = r"<Comment>(.*?)In the software, each file must strictly follow a markdown code block format"
    match = re.search(pattern, utterance, re.DOTALL)
    if match:
        extracted_text = match.group(1).strip()
        commentlist.append(extracted_text)



for i in range(len(commentlist)):
    code_old = codelist[i]
    code_new = codelist[i+1]
    diff = difflib.unified_diff(code_old.splitlines(), code_new.splitlines(), lineterm='', fromfile='Old', tofile='New')
    diff = '\n'.join(diff)
    difflist.append(diff)

print(difflist)

for i in range(len(difflist)):
    print("Comment:\n", commentlist[i])
    print("Diff:\n", difflist[i])
    print("------------------------------------------------------")

