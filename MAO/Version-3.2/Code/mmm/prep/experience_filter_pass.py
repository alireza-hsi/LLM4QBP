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
        for experience in experiences:
            targetMID = experience["targetMID"]
            _nodes = [node for node in nodes if node["mID"] == targetMID]
            assert len(_nodes) == 1
            node = _nodes[0]
            code_lines = node["code"].split("\n")
            code_lines = [line.lower().strip() for line in code_lines]
            pass_flag = "pass".lower() in code_lines or "TODO".lower() in code_lines
            if not pass_flag:
                new_experiences.append(experience)
        memorypiece["experiences"] = new_experiences

    content = [memorypiece for memorypiece in content if len(memorypiece["experiences"])>0]
    print("len(content)=", len(content))

    experiences = [experience for memorypiece in content for experience in memorypiece["experiences"]]
    print("len(experiences)=", len(experiences))


filtered_directory = "./mmm/memory/MemoryCards.qc.json"
with open(filtered_directory, 'w') as file:
    json.dump(content, file)
    file.close()
