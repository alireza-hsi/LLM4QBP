# =========== Copyright 2023 @ CAMEL-AI.org. All Rights Reserved. ===========
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# =========== Copyright 2023 @ CAMEL-AI.org. All Rights Reserved. ===========
import argparse
import logging
import os
import sys
import json
root = os.path.dirname(__file__)
sys.path.append(root)

from camel.typing import ModelType
from MAO.chat_chain import ChatChain

def get_config(company):
    """Return configuration json files for ChatChain"""
    config_dir = os.path.join(root, "CompanyConfig", company)
    default_config_dir = os.path.join(root, "CompanyConfig", "Default")

    config_files = [
        "ChatChainConfig.json",
        "PhaseConfig.json",
        "RoleConfig.json"
    ]

    config_paths = []
    for config_file in config_files:
        company_config_path = os.path.join(config_dir, config_file)
        default_config_path = os.path.join(default_config_dir, config_file)
        config_paths.append(company_config_path if os.path.exists(company_config_path) else default_config_path)

    return tuple(config_paths)

def parse_args():
    parser = argparse.ArgumentParser(description='argparse')
    parser.add_argument('--config', type=str, default="Default",
                        help="Name of config, which is used to load configuration under CompanyConfig/")
    parser.add_argument('--org', type=str, default="DefaultOrganization",
                        help="Name of organization, your software will be generated in WareHouse/name_org_timestamp")
    parser.add_argument('--task', type=str, default="",
                        help="Prompt of software")
    parser.add_argument('--task-file', type=str, help="Path to file containing the task description")
    parser.add_argument('--name', type=str, default="",
                        help="Name of software, your software will be generated in WareHouse/name_org_timestamp")
    parser.add_argument('--model', type=str, default="GPT_4",
                        help="GPT Model, choose from {'GPT_3_5_TURBO','GPT_4','GPT_4_32K','GPT_4o', GPT_4o1}")
    args = parser.parse_args()
    
    if args.task_file:
        with open(args.task_file, 'r') as f:
            args.task = f.read().strip()
    
    return args

if __name__ == "__main__":
    args = parse_args()
    
    # ----------------------------------------
    #          Init ChatChain
    # ----------------------------------------
    config_path, config_phase_path, config_role_path = get_config(args.config)
    
    # Convert model string to ModelType
    args2type = {
        'GPT_3_5_TURBO': ModelType.GPT_3_5_TURBO,
        'GPT_4': ModelType.GPT_4,
        'GPT_4_32K': ModelType.GPT_4_32k,
        'GPT_4o': ModelType.GPT_4o,
        'GPT_4o1': ModelType.GPT_4o1
    }
    
    chat_chain = ChatChain(
        config_path=config_path,
        config_phase_path=config_phase_path,
        config_role_path=config_role_path,
        task_prompt=args.task,
        project_name=args.name,
        org_name=args.org,
        model_type=args2type[args.model]
    )
    
    # ----------------------------------------
    #          Init Log  
    # ----------------------------------------
    log_filepath = os.path.join(chat_chain.chat_env.env_dict["directory"], "log.txt")
    chat_chain.log_filepath = log_filepath  # Store the filepath in chat_chain
    logging.basicConfig(
        filename=log_filepath,
        level=logging.INFO,
        format='[%(asctime)s %(levelname)s] %(message)s',
        datefmt='%Y-%d-%m %H:%M:%S',
        encoding="utf-8"
    )
    
    # ----------------------------------------
    #          Pre Processing  
    # ----------------------------------------
    print("!!")
    print('API=', os.environ['OPENAI_API_KEY'])
    chat_chain.pre_processing()
    
    # ----------------------------------------
    #          Personnel Recruitment
    # ----------------------------------------
    chat_chain.make_recruitment()
    
    # ----------------------------------------
    #          Chat Chain  
    # ----------------------------------------
    chat_chain.execute_chain()
    
    # ----------------------------------------
    #          Post Processing  
    # ----------------------------------------
    chat_chain.post_processing()

    # After post_processing()
    bpmn_path = os.path.join(chat_chain.chat_env.env_dict["directory"], "process.bpmn")
    print(bpmn_path)