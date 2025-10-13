import os
import json

# the directory should be a file folder path, which contains several MemoryCards.json for different categories 
# return one json, containing the first n pieces of memory in each MemoryCards.json
def train_split(directory: str, n: int):
    dir_train = "./mmm/memory/train.json"
    file_names = os.listdir(directory)
    print(file_names)
    train_content = []

    for file_name in file_names:
        # print(len(file_names))
        file_path = os.path.join(directory,file_name)
        with open(file_path) as file:
            content = json.load(file)
            # for piece in content:
            #         print(piece.get("dir"))
            if len(content) >=n:
                print(len(content))
                for i in range(0,n):
                    train_content.append(content[i])
                    print(content[i].get("dir"))
                print(len(train_content))
                print("load {} into training set".format(file_name))
                # for piece in content:
                #     print(piece.get("dir"))
            else:
                print("The {} length is shorter than {}".format(file_name, n))
    
    with open(dir_train,'w') as file:
        print(len(train_content))
        json.dump(train_content, file)
        file.close()
    
# the directory should be a file folder path, which contains several MemoryCards.json for different categories 
# return one json, containing the [m,n) (index from 0) pieces of memory in each MemoryCards.json
def val_split(directory: str, m: int, n: int):
    dir_train = "./mmm/memory/val.json"
    file_names = os.listdir(directory)
    print(file_names)
    val_content = []

    for file_name in file_names:
        file_path = os.path.join(directory,file_name)
        with open(file_path) as file:
            content = json.load(file)
            if len(content) >=n:
                val_content.append(content[m:n])
                print("load {} into validation set".format(file_name))
            else:
                print("The {} length is shorter than {}".format(file_name, n))
    
    with open(dir_train,'w') as file:
        json.dump(val_content, file)
        file.close()
        
# the directory should be a file folder path, which contains several MemoryCards.json for different categories 
# return one json, containing the first [m,n) (index from 0) pieces of memory in each MemoryCards.json
def test_split(directory: str, m: int, n: int):
    dir_train = "./mmm/memory/test.json"
    file_names = os.listdir(directory)
    print(file_names)
    test_content = []

    for file_name in file_names:
        file_path = os.path.join(directory,file_name)
        with open(file_path) as file:
            content = json.load(file)
            if len(content) >=n:
                test_content.append(content[m:n])
                print("load {} into testing set".format(file_name))
            else:
                print("The {} length is shorter than {}".format(file_name, n))
    
    with open(dir_train,'w') as file:
        json.dump(test_content, file)
        file.close()

train_split("./mmm/memory-dataset",20)