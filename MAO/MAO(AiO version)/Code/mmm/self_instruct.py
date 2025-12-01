# li jia hao
# 时间：2023/10/8 8:52
from experience import Experience
from utils import get_easyDict_from_filepath,chat_completion_request
from graph import Graph
import os
import time

#读取经验
cfg = get_easyDict_from_filepath("./mmm/config.yaml")

# directory = "./WareHouse/Destruction_Dash_TaskV6_Action_Game_20231009140546"  # Gomoku

directory_path = "./WareHouse"
first_level_subdirs = [os.path.join(directory_path, d) for d in os.listdir(directory_path) if os.path.isdir(os.path.join(directory_path, d))]
for subdir in first_level_subdirs:
    directory = subdir

    graph = Graph()
    graph.create_from_warehouse(directory)

    experience = Experience(graph, directory)
    if cfg.experience.reap_zombie:
        experience.reap_zombie()
        #graph.print()
    experience.estimate()
    experiences = experience.extract_thresholded_experiences()

    # #打印经验中的instructionPath
    # print("-----------------")
    # for experience in experiences:
    #     print(experience.instructionPath)

    #将经验中的instructionPath合并传入字符串instructionPath
    """no instructionpath in experience after update
    """
    
    #instructionPath=""
    #for experience in experiences:
        #将experience.instructionPath转化为字符串再传入instructionPath
        #experience.instructionPath="".join(experience.instructionPath)
        #instructionPath=instructionPath+experience.instructionPath

    #如果经验为空，进入下一个文件夹
    if len(experiences)==0:
        continue
    first_experience=experiences[0]
    first_sourceMID=first_experience.sourceMID
    first_targetMID=first_experience.targetMID

    #通过结点的id找到结点的code
    for node in graph.nodes.values():
        if node.mID == first_sourceMID:
            vi = node.code
        if node.mID == first_targetMID:
            vj = node.code


    # #self_instruct(vi, vj) -> str
    # while True:
    #     if vi=="":
    #         response = chat_completion_request(messages=[{"role": "system",
    #                                                       "content": "What instructions should I give you, you will generate this code for me:" + vj + "\n Note: The instructions you generate should include, but are not limited to:\n Modules and Classes:Specify the required modules and the names, attributes, and methods of classes to be created within each module. Describe the purpose and functionality of each class.\n Data Structures:If specific data structures are needed, specify their names, attributes, and methods.\n Main Program Flow:Describe the main flow of the program, including the steps to initialize and call other modules, classes, and methods in the main file (e.g., main.py). Explain the logical flow of the program during runtime.\n Input and Output:Define how the program should receive input, whether from users or external data sources. Also, describe the expected outputs or behaviors of the program.\n Exception Handling:Explain how to handle potential errors or exceptions that may occur during program execution to ensure stability and robustness.\nExternal Libraries and Dependencies:If you need to use external libraries or dependencies, clearly specify the names, versions, and purposes of these libraries.\n Output the instructions directly."}])
    #     else:
    #         response = chat_completion_request(messages=[{"role":"system",
    #                                                       "content": "What instructions should I give you, you will upgrade this first version code:"+vi+" to this final version code:"+vj+"\n Note:The instructions you generate should include, but are not limited to:\n Modules and Classes:Specify the modules to be added and the names, attributes, and methods of classes to be added or modified within each module. Describe the purpose and functionality of the classes to be added or modified.\n Data Structures:If specific data structures need to be added or modified, specify these data structures, including their names, attributes, and methods.\n Main Program Flow:Describe the main flow of the program, including the steps to initialize and call other modules, classes, and methods in the main file (e.g., main.py). Explain the logical flow of the program during runtime.\n Input and Output:Define how the program should receive input, whether from users or external data sources. Also, describe the expected outputs or behaviors of the program.\n Exception Handling:Explain how to handle potential errors or exceptions that may occur during program execution to ensure stability and robustness.\n External Libraries and Dependencies:If you need to use external libraries or dependencies, clearly specify the names, versions, and purposes of these libraries. "}])
    #     if "choices" in response and response["choices"]:
    #         break
    #     time.sleep(10)
    # #读取response中的instruction
    # instruction = response["choices"][0]["message"]["content"]
    # if vi == "":
    #     instruction_path = os.path.join(directory, "instruction.txt")
    # else:
    #     instruction_path = os.path.join(directory, "update_instruction.txt")
    #
    # with open(instruction_path,"w") as f:
    #     f.write(instruction)
    # print("instruction.txt is saved in "+directory+"!")
    #
    # #利用instruction生成新的code，命名为new_code.py存到directory对应文件夹中
    # while True:
    #     if vi == "":
    #         response = chat_completion_request(messages=[{"role": "system", "content": "Use the following instructions to generate the appropriate runnable software code:"+instruction}])
    #
    #     else:
    #         response = chat_completion_request(messages=[{"role": "system", "content": "upgrade this first version code:\n" + vi + "\n with the following instruction:\n" + instruction}])
    #
    #     if "choices" in response and response["choices"]:
    #         break
    #
    # code = response["choices"][0]["message"]["content"]
    # if vi == "":
    #     code_path = os.path.join(directory, "new_code.py")
    # else:
    #     code_path = os.path.join(directory, "update_code.py")
    # with open(code_path,"w") as f:
    #     f.write(code)
    # print("new_code.py is saved in "+directory+"!")


    #self_instruct(vi, vj, path) -> str
    while True:
        if vi=="":
            response = chat_completion_request(messages=[{"role": "system","content": vj +"\n This final version code is generated through multiple iterations of code based on the following instructions:\n" + instructionPath + "\n What instructions which I should give you, you will generate this code for me? The instructions you generate should include, but are not limited to:\n Modules and Classes:Specify the required modules and the names, attributes, and methods of classes to be created within each module. Describe the purpose and functionality of each class.\n Data Structures:If specific data structures are needed, specify their names, attributes, and methods.\n Main Program Flow:Describe the main flow of the program, including the steps to initialize and call other modules, classes, and methods in the main file (e.g., main.py). Explain the logical flow of the program during runtime.\n Input and Output:Define how the program should receive input, whether from users or external data sources. Also, describe the expected outputs or behaviors of the program.\n Exception Handling:Explain how to handle potential errors or exceptions that may occur during program execution to ensure stability and robustness.\nExternal Libraries and Dependencies:If you need to use external libraries or dependencies, clearly specify the names, versions, and purposes of these libraries.\n Output instruction directly."}])
        else:
            response = chat_completion_request(messages=[{"role":"system","content": vj + " \n This final version code is generated from this first version code:" + vi+ " \n and through  multiple iterations of code based on the following instructions:\n" + instructionPath +"If I want to generate the final version code from the first version code using a given set of instructions,What instructions which I should give you，The instructions you generate should include, but are not limited to：\n Modules and Classes:Specify the modules to be added and the names, attributes, and methods of classes to be added or modified within each module. Describe the purpose and functionality of the classes to be added or modified.\n Data Structures:If specific data structures need to be added or modified, specify these data structures, including their names, attributes, and methods.\n Main Program Flow:Describe the main flow of the program, including the steps to initialize and call other modules, classes, and methods in the main file (e.g., main.py). Explain the logical flow of the program during runtime.\n Input and Output:Define how the program should receive input, whether from users or external data sources. Also, describe the expected outputs or behaviors of the program.\n Exception Handling:Explain how to handle potential errors or exceptions that may occur during program execution to ensure stability and robustness.\n External Libraries and Dependencies:If you need to use external libraries or dependencies, clearly specify the names, versions, and purposes of these libraries."}])
        if "choices" in response and response["choices"]:
            break
        time.sleep(10)

    #读取response中的instruction
    Pathinstruction = response["choices"][0]["message"]["content"]
    if vi == "":
        Pathinstruction_path = os.path.join(directory, "PathinstructionStar.txt")
    else:
        Pathinstruction_path = os.path.join(directory, "update_PathinstructionStar.txt")

    with open(Pathinstruction_path,"w") as f:
        f.write(Pathinstruction)

    #利用instruction生成新的code，命名为new_code.py存到directory对应文件夹中
    while True:
        if vi == "":
            codes = chat_completion_request(messages=[{"role": "system", "content": "Use the instructions below to generate the appropriate runnable software code:"+Pathinstruction}])

        else:
            codes = chat_completion_request(messages=[{"role": "system", "content": "upgrade this first version code:\n" + vi + "\n with the following instruction:\n" + Pathinstruction}])

        if "choices" in codes and codes["choices"]:
            break
        time.sleep(10)

    Pathcode = codes["choices"][0]["message"]["content"]
    if vi == "":
        code_path = os.path.join(directory, "PathinstructionStar_new_code.py")
    else:
        code_path = os.path.join(directory, "PathinstructionStar_update_code.py")
    with open(code_path,"w") as f:
        f.write(Pathcode)
