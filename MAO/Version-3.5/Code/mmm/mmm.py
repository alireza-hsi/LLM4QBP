
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
cfg = get_easyDict_from_filepath("./mmm/config.yaml")

# directory = "./WareHouse/Gomoku_DefaultOrganization_20231018100210" # Gomoku
# directory = "./WareHouse/Gomoku_DefaultOrganization_20231005100134" # Snake
# directory = "./WareHouse/Gomoku_DefaultOrganization_20231007181138" # Gomoku
# directory = "./WareHouse/Gomoku_DefaultOrganization_20231018100753" # Gomoku
# directory = "./Warehouse/Gomoku_DefaultOrganization_20231018153011"
# directory = "./Warehouse/Gomoku_DefaultOrganization_20231018154903"
# directory = "./Warehouse/snake_DefaultOrganization_20231018160749"
task = ["./WareHouse/Video_Enhancer_DefaultOrganization_20231110113306",
"./WareHouse/Video_Memories_Maker_DefaultOrganization_20231110131504",
"./WareHouse/Video_Mosaic_Creator_DefaultOrganization_20231110171741",
"./WareHouse/Video_Scene_Recognition_Viewer_DefaultOrganization_20231112142414",
"./WareHouse/Video_Slicer_DefaultOrganization_20231112160053"]

for directory in task:
    folder_path = "mmm/logs/Video"
    if not os.path.exists(folder_path):
        os.mkdir(folder_path)
    log_filename = folder_path+"/mmm_{}.log".format(directory.split("/")[-1])
    print(log_filename)

    root_logger = logging.getLogger()
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    file_handler = logging.FileHandler(log_filename, mode='w', encoding='utf-8')
    formatter = logging.Formatter('[%(asctime)s %(levelname)s] %(message)s', datefmt='%Y-%d-%m %H:%M:%S')
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)
    root_logger.setLevel(logging.INFO)

    log_and_print_online("[Config]:"+str(cfg))
    print("directory:", directory)
    print("directory:", directory)
    graph = Graph()
    graph.create_from_warehouse(directory)
    graph.print()

    experience = Experience(graph, directory)
    if cfg.experience.reap_zombie:
        experience.reap_zombie()
        graph.print()
    experience.estimate()
    experiences = experience.extract_thresholded_experiences()

    # memory upload 
    # memory = Memory()
    # memory.upload()
    # memory.upload_from_experience(experience)

