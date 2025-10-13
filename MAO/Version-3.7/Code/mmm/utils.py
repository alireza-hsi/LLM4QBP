import subprocess
import json
import yaml
import time
import logging
from easydict import EasyDict
import openai
from openai import OpenAI

client = OpenAI(api_key="sk-oYlPfsN4LrwmXlNTAaEbC3676e5e458dBbFdE1A548973c46")
import numpy as np
import faiss
import requests
import os
from abc import ABC, abstractmethod
import tiktoken
from typing import Any, Dict
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    wait_fixed
)


def getFilesFromType(sourceDir, filetype):
    files = []
    for root, directories, filenames in os.walk(sourceDir):
        for filename in filenames:
            if filename.endswith(filetype):
                files.append(os.path.join(root, filename))
    return files

def cmd(command: str):
    print(">> {}".format(command))
    text = subprocess.run(command, shell=True, text=True, stdout=subprocess.PIPE).stdout
    return text

def get_easyDict_from_filepath(path: str):
    # print(path)
    if path.endswith('.json'):
        with open(path, 'r', encoding="utf-8") as file:
            config_map = json.load(file, strict=False)
            config_easydict = EasyDict(config_map)
            return config_easydict
    if path.endswith('.yaml'):
        file_data = open(path, 'r', encoding="utf-8").read()
        config_map = yaml.load(file_data, Loader=yaml.FullLoader)
        config_easydict = EasyDict(config_map)
        return config_easydict
    return None



# for test
def cosine_similarity(a, b):
    return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))



def calc_max_token(messages, model):
    string = "\n".join([message["content"] for message in messages])
    encoding = tiktoken.encoding_for_model(model)
    num_prompt_tokens = len(encoding.encode(string))
    gap_between_send_receive = 50
    num_prompt_tokens += gap_between_send_receive

    num_max_token_map = {
        "gpt-3.5-turbo": 4096,
        "gpt-3.5-turbo-16k": 16384,
        "gpt-3.5-turbo-0613": 4096,
        "gpt-3.5-turbo-16k-0613": 16384,
        "gpt-4": 8192,
        "gpt-4-0613": 8192,
        "gpt-4-32k": 32768,
    }
    num_max_token = num_max_token_map[model]

    num_max_completion_tokens = num_max_token - num_prompt_tokens

    return num_max_completion_tokens



def chat_completion_request(messages, model="gpt-3.5-turbo-16k-0613", model_config_dict: Dict = None):
    print("getting instructionstar......")
    num_max_completion_tokens = calc_max_token(messages, model)
    string = "\n".join([message["content"] for message in messages])
    encoding = tiktoken.encoding_for_model(model.value)
    num_prompt_tokens = len(encoding.encode(string))
    gap_between_send_receive = 15 * len(messages)
    num_prompt_tokens += gap_between_send_receive

    if model_config_dict == None:
        model_config_dict = {"temperature": 0.2,
                             "top_p": 1.0,
                             "n": 1,
                             "stream": False,
                             "frequency_penalty": 0.0,
                             "presence_penalty": 0.0,
                             "logit_bias": {},
                             }

    json_data = {
        "model": model,
        "messages": messages,
        "max_tokens": num_max_completion_tokens,
        "temperature": model_config_dict["temperature"],
        "top_p": model_config_dict["top_p"],
        "n": model_config_dict["n"],
        "stream": model_config_dict["stream"],
        "frequency_penalty": model_config_dict["frequency_penalty"],
        "presence_penalty": model_config_dict["presence_penalty"],
        "logit_bias": model_config_dict["logit_bias"],
    }
    try:
        if model == "gpt-4":
            url = "http://120.92.10.46:8080/chat"
        else:
            url = "http://47.254.22.102:8989/chat"
        private_response = requests.post(url=url,
                                      json=json_data,
                                       headers={"Content-Type": "application/json"},
                                        timeout=300)
        response = json.loads(private_response.text)
        return response
    except Exception as e:
        print("Unable to generate ChatCompletion response")
        print(f"OpenAI calling Exception: {e}")
        return e
        
class ModelBackend(ABC):
    r"""Base class for different model backends.
    May be OpenAI API, a local LLM, a stub for unit tests, etc."""

    @abstractmethod
    def run(self, *args, **kwargs) -> Dict[str, Any]:
        r"""Runs the query to the backend model.

        Raises:
            RuntimeError: if the return value from OpenAI API
            is not a dict that is expected.

        Returns:
            Dict[str, Any]: All backends must return a dict in OpenAI format.
        """
        pass

class OpenAIModel(ModelBackend):
    r"""OpenAI API in a unified ModelBackend interface."""

    def __init__(self, model_type, model_config_dict: Dict=None) -> None:
        super().__init__()
        self.model_type = model_type
        self.model_config_dict = model_config_dict
        if self.model_config_dict == None:
            self.model_config_dict = {"temperature": 0.2,
                                "top_p": 1.0,
                                "n": 1,
                                "stream": False,
                                "frequency_penalty": 0.0,
                                "presence_penalty": 0.0,
                                "logit_bias": {},
                                }
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.total_tokens = 0

    @retry(wait=wait_exponential(min=5, max=60), stop=stop_after_attempt(5))
    def run(self, messages) :
        current_retry = 0
        max_retry = 5
        # TODO: The 'openai.api_base' option isn't read in the client API. You will need to pass it when you instantiate the client, e.g. 'OpenAI(api_base="https://sailaoda.cn/v1")'
        # openai.api_base = "https://sailaoda.cn/v1"

        string = "\n".join([message["content"] for message in messages])
        encoding = tiktoken.encoding_for_model(self.model_type)
        num_prompt_tokens = len(encoding.encode(string))
        gap_between_send_receive = 15 * len(messages)
        num_prompt_tokens += gap_between_send_receive

        num_max_token_map = {
            "gpt-3.5-turbo": 4096,
            "gpt-3.5-turbo-16k": 16384,
            "gpt-3.5-turbo-0613": 4096,
            "gpt-3.5-turbo-16k-0613": 16384,
            "gpt-4": 8192,
            "gpt-4-0613": 8192,
            "gpt-4-32k": 32768,
        }
        # messages = [{"role": "user", "content": "Hello"}]
        response = client.chat.completions.create(messages = messages,
        model = "gpt-3.5-turbo-16k",
        temperature = 0.2,
        top_p = 1.0,
        n = 1,
        stream = False,
        frequency_penalty = 0.0,
        presence_penalty = 0.0,
        logit_bias = {},
        )
        response_text = response['choices'][0]['message']['content']



        num_max_token = num_max_token_map[self.model_type]
        num_max_completion_tokens = num_max_token - num_prompt_tokens
        self.model_config_dict['max_tokens'] = num_max_completion_tokens
        # response = openai.ChatCompletion.create(*args, **kwargs,
        #                                         model=self.model_type,
        #                                         **self.model_config_dict)
        log_and_print_online(
            "InstructionStar generation:\n**[OpenAI_Usage_Info Receive]**\nprompt_tokens: {}\ncompletion_tokens: {}\ntotal_tokens: {}\n".format(
                response["usage"]["prompt_tokens"], response["usage"]["completion_tokens"],
                response["usage"]["total_tokens"]))
        self.prompt_tokens += response["usage"]["prompt_tokens"]
        self.completion_tokens += response["usage"]["completion_tokens"]
        self.total_tokens += response["usage"]["total_tokens"]
        
        if not isinstance(response, Dict):
            raise RuntimeError("Unexpected return from OpenAI API")
        return response

"""
 This function is currently unused but is being kept for future extensions.

def eval_embedding_L2distance(example:str, origin:str, generated:str):
    embedding_method = OpenAIEmbedding()
    embedding_data = []

    example = embedding_method.get_code_embedding(example)
    origin = embedding_method.get_code_embedding(origin)
    generated = embedding_method.get_code_embedding(generated)

    embedding_data.append(example)
    embedding_data.append(origin)
    embedding_data.append(generated)
    embedding_data = np.array(embedding_data, dtype=np.float32)
    example_query = np.array(example, dtype=np.float32).reshape(1,-1)
    origin_query = np.array(origin, dtype=np.float32).reshape(1,-1)
    generated_query = np.array(generated, dtype=np.float32).reshape(1,-1)

    faiss.normalize_L2(example_query)
    faiss.normalize_L2(origin_query)
    faiss.normalize_L2(generated_query)
    faiss.normalize_L2(embedding_data)

    index = faiss.IndexFlatL2(embedding_data.shape[1])
    index.add(embedding_data)

    distance, indices = index.search(example_query,3)
    print("example query:", distance,indices)
    distance, indices = index.search(origin_query,3)
    print("origin query:", distance,indices)
    
    distance, indices = index.search(generated_query,3)
    print("generated query:", distance,indices)

"""
    
def now():
    return time.strftime("%Y%m%d%H%M%S", time.localtime())

def log_and_print_online(content=None):
    if  content is not None:
        print(content)
        logging.info(content)
