
import argparse
from graph import Graph
from experience import Experience
from utils import get_easyDict_from_filepath,now ,log_and_print_online
from memory import Memory
from prep.dataset_dir import get_filenameList
import sys
import os 
import logging
sys.path.append(os.path.join(os.getcwd(),"mmm"))
category =   "Reference_Books"


cfg = get_easyDict_from_filepath("./mmm/config.yaml")

fileList,filenameList = get_filenameList(category)
print(fileList)
index = 0

for i in range(index,len(fileList)):
    directory = fileList[i]
    print(directory)
    filename = filenameList[i]
    print(filename)
    folder_path = "mmm/logs/"+category
    if not os.path.exists(folder_path):
        os.mkdir(folder_path)
    log_filename = folder_path+"/mmm_{}.log".format(filename)

    root_logger = logging.getLogger()
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    file_handler = logging.FileHandler(log_filename, mode='w', encoding='utf-8')
    formatter = logging.Formatter('[%(asctime)s %(levelname)s] %(message)s', datefmt='%Y-%d-%m %H:%M:%S')
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)
    root_logger.setLevel(logging.INFO)

    log_and_print_online("[Config]:"+str(cfg))

    graph = Graph()
    graph.create_from_log(directory)
    graph.print()

    experience = Experience(graph, directory)
    if cfg.experience.reap_zombie:
        experience.reap_zombie()
        graph.print()
    experience.estimate()
    experiences = experience.extract_thresholded_experiences()


