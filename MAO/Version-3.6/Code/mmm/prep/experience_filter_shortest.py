import json  
import os
# filter memorycards.json by experiences valueGain, delete experience whose valueGain is smaller than filter_threshold  
filter_threshold = 0.9

directory = "./mmm/memory/MemoryCards.json"
content = []
with open(directory) as file:
    content = json.load(file)
    print("len(content)=", len(content))

    experiences = [experience for memorypiece in content for experience in memorypiece["experiences"]]
    print("len(experiences)=", len(experiences))

    for memorypiece in content:
        nodes = memorypiece["nodes"]
        experiences = memorypiece["experiences"]
        new_experiences = []
        n = len(experiences)
        sourceMID = experiences[0]["sourceMID"]
        targetMID = experiences[-1]["targetMID"]
        for experience in experiences:
            if experience["sourceMID"] == sourceMID and experience["targetMID"]==targetMID:
                new_experiences.append(experience)
                break
        memorypiece["experiences"] = new_experiences

    content = [memorypiece for memorypiece in content if len(memorypiece["experiences"])>0]
    print("len(content)=", len(content))

    experiences = [experience for memorypiece in content for experience in memorypiece["experiences"]]
    print("len(experiences)=", len(experiences))


filtered_directory = "./mmm/memory/MemoryCards.dyf.json"
with open(filtered_directory, 'w') as file:
    json.dump(content, file)
    file.close()
