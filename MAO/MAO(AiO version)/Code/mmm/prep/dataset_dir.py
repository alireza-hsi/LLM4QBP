import os
import sys
import re

# get filedir list form dataset directory
# input string is the task category,such as "Video"
def get_filenameList(str):

    directory = r"C:\Users\Dang_Yufan\mmm\dataset\full" # the file folder path of dataset
    file_names = os.listdir(directory)
    # print(file_names)
    regex = r"\_"+str+"\_\d"
    regex1 = r"NewFeature"
    dir_list = []
    withfeature_roleplaying_list = []
    filename_list = []
    for file_name in file_names:
        if re.search(regex,file_name) :
            if re.search (regex1,file_name):
                withfeature_roleplaying_list.append(file_name)
            else:
                dir_list.append(os.path.join(directory,file_name))
                filename_list.append(file_name)
    print(len(dir_list))
    for i in range(len(dir_list)):
        print(filename_list[i])
    print(filename_list)
    
    return  dir_list,filename_list

def get_task(str):
    
    directory = r"C:\Users\Dang_Yufan\mmm\dataset\full" # the file folder path of dataset
    file_names = os.listdir(directory)
    # print(file_names)
    regex = r"\_"+str+"\_\d"
    regex1 = r"NewFeature"
    dir_list = []
    withfeature_roleplaying_list = []
    filename_list = []
    for file_name in file_names:
        if re.search(regex,file_name) :
            if re.search (regex1,file_name):
                withfeature_roleplaying_list.append(file_name)
            else:
                dir_list.append(os.path.join(directory,file_name))
                filename_list.append(file_name)
    print(len(dir_list))
    # print(filename_list)

    name_list = []
    task_list = []

    for name in filename_list:
        regex = "(.*)\_Task"
        matches = re.finditer(regex, name, re.DOTALL)
        for match in matches:
            name = match.group(1)
        name_list.append(name)

    for directory in dir_list:
        filenames = os.listdir(directory)
        filename = [filename for filename in filenames if filename.endswith(".prompt")][0]
        task_prompt = open(os.path.join(directory, filename), "r").read().strip()
        task_list.append(task_prompt)
    print(len(task_list),len(name_list))
    return  task_list, name_list

get_task("Role_Playing_Game")                                                                                                       