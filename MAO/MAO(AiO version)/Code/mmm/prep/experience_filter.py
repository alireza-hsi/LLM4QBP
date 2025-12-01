import json  
import os
# filter memorycards.json by experiences valueGain, delete experience whose valueGain is smaller than filter_threshold  
filter_threshold = 0.9

directory = r"C:\Users\Dang_Yufan\mmm\ChatDev\mmm\memory\MemoryCards.json" # original .json dir 
content = []
with open(directory) as file:
    content = json.load(file)
    new_content = []
    for memorypiece in content:
        experiences = memorypiece.get("experiences")
        filtered_experienceList = []
        
        if experiences != None:
            print("origin:",len(experiences))
            for experience in experiences:
                valueGain = experience.get("valueGain")
                print(valueGain)
                if valueGain >= filter_threshold:
                    filtered_experienceList.append(experience)
            print(len(experiences))
            memorypiece["experiences"] = filtered_experienceList
            new_content.append(memorypiece)
        else:
            new_content.append(memorypiece)
    file.close()
filtered_directory = r"C:\Users\Dang_Yufan\mmm\ChatDev\mmm\memory\MemoryCards_filtered_{}.json".format(filter_threshold) # filtered .json dir

with open(filtered_directory,'w') as file:
    json.dump(new_content, file)
    file.close()

