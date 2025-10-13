import json  
import os
import copy
def index():
    directory = "./mmm/memory/MemoryCards_filtered0.9.json" # original .json dir 
    content = []
    with open(directory) as file:
        content = json.load(file)
        new_content = []
        for index,memorypiece in enumerate(content):
            print(index)
            new_memorpiece = memorypiece
            new_memorpiece["index"] = index
            new_memorpiece["total"] = index+1
            new_content.append(new_memorpiece)
        file.close()
    filtered_directory = "./mmm/memory/MemoryCards_filtered0.9.json" # filtered .json dir

    with open(filtered_directory,'w') as file:
        json.dump(new_content, file)
        file.close()

def separate():
    directory = "./mmm/memory/MemoryCards_Family_Kids copy.json" # original .json dir 
    content = []
    with open(directory) as file:
        content = json.load(file)
        new_content1 = content[0:30]
        new_content2 = content[30:60]
        
    filtered_directory = "./mmm/memory/MemoryCards_Development.json" # filtered .json dir

    with open(filtered_directory,'w') as file:
        json.dump(new_content2, file)
        file.close()
    
    filtered_directory = "./mmm/memory/MemoryCards_Family_Kids.json" # filtered .json dir

    with open(filtered_directory,'w') as file:
        json.dump(new_content1, file)
        file.close()
    
def delete(directory:str,idx: int):
    print(os.path.exists(directory))
    merged_dic = []
    with open(directory) as file:
        content = json.load(file)
    print(len(content))
    if len(content)<=800:
        return 

    with open(directory,"w") as file:
        if len(content) != 0 and isinstance(content,list):
            for index,t in enumerate(content):
                if isinstance(t,list):
                    for subindex,subt in enumerate(t):
                        if len(subt)!=0:
                            merged_dic.append(subt)
                elif len(t)!=0 :
                    merged_dic.append(t)
                    index = merged_dic[-1]["total"]
        elif len(content) != 0:
            merged_dic.append(content)
            index = 1
                
        if idx >= len(merged_dic):
            json.dump(merged_dic,file)
        else :
            merged_dic.pop(idx)
            json.dump(merged_dic,file)
        file.close()


delete("./mmm/memory/MemoryCards.json",800)