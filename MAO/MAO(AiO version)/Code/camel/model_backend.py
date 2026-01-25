# =========== Copyright 2023 @ CAMEL-AI.org. All Rights Reserved. ===========
# Licensed under the Apache License, Version 2.0 (the “License”);
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an “AS IS” BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# =========== Copyright 2023 @ CAMEL-AI.org. All Rights Reserved. ===========
from abc import ABC, abstractmethod
from typing import Any, Dict
import os
import openai
from openai import OpenAI
#from openai.types.chat import ChatCompletion

client = OpenAI(
    api_key=os.environ['OPENAI_API_KEY'],
    # Remove or comment out the base_url line
    # base_url="https://yeysai.com/v1/",
)
import tiktoken

from camel.typing import ModelType
from MAO.utils import log_and_print_online


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

    def __init__(self, model_type: ModelType, model_config_dict: Dict) -> None:
        super().__init__()
        self.model_type = model_type
        self.model_config_dict = model_config_dict

    def _log_usage(self, response: Dict[str, Any]) -> None:
        usage = response.get("usage", {}) or {}

        # Chat Completions shape
        if "prompt_tokens" in usage or "completion_tokens" in usage:
            prompt = usage.get("prompt_tokens", 0)
            completion = usage.get("completion_tokens", 0)
            total = usage.get("total_tokens", prompt + completion)

        # Responses shape
        else:
            prompt = usage.get("input_tokens", usage.get("prompt_tokens", 0))
            completion = usage.get("output_tokens", usage.get("completion_tokens", 0))
            total = usage.get("total_tokens", prompt + completion)

        log_and_print_online(
            "**[OpenAI_Usage_Info Receive]**\n"
            f"prompt_tokens/input_tokens: {prompt}\n"
            f"completion_tokens/output_tokens: {completion}\n"
            f"total_tokens: {total}\n"
        )   

    def responses_to_chatcompletions_dict(self, resp: Dict[str, Any]) -> Dict[str, Any]:
        """
        Convert OpenAI Responses API result (model_dump dict) into the legacy
        Chat Completions-style dict expected by downstream code.
        """
        # ---- Extract text output ----
        text_parts = []

        # Responses commonly: output: [{content: [{type:"output_text", text:"..."}], role:"assistant"}]
        for item in resp.get("output", []) or []:
            for c in item.get("content", []) or []:
                if c.get("type") in ("output_text", "text"):
                    if "text" in c and c["text"]:
                        text_parts.append(c["text"])

        content = "\n".join(text_parts).strip()

        # Fallbacks (SDK variations)
        if not content:
            # Some SDKs expose convenience fields
            maybe = resp.get("output_text")
            if isinstance(maybe, str) and maybe.strip():
                content = maybe.strip()

        # ---- Usage normalization ----
        usage = resp.get("usage", {}) or {}
        prompt = usage.get("prompt_tokens", usage.get("input_tokens", 0))
        completion = usage.get("completion_tokens", usage.get("output_tokens", 0))
        total = usage.get("total_tokens", prompt + completion)

        # ---- Build Chat Completions-like shape ----
        return {
            "id": resp.get("id", ""),
            "object": "chat.completion",
            "created": resp.get("created", None),
            "model": resp.get("model", None),
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {
                        "role": "assistant",
                        "content": content,
                    },
                }
            ],
            "usage": {
                "prompt_tokens": prompt,
                "completion_tokens": completion,
                "total_tokens": total,
            },
        }
    def run(self, *args, **kwargs) -> Dict[str, Any]:
        string = "\n".join([message["content"] for message in kwargs["messages"]])
        encoding = tiktoken.encoding_for_model(self.model_type.value_for_tiktoken) 
        num_prompt_tokens = len(encoding.encode(string))
        gap_between_send_receive = 15 * len(kwargs["messages"])
        num_prompt_tokens += gap_between_send_receive

        num_max_token_map = {
            "gpt-3.5-turbo": 4096,
            "gpt-3.5-turbo-16k": 16384,
            "gpt-3.5-turbo-0613": 4096,
            "gpt-3.5-turbo-16k-0613": 16384,
            "gpt-4": 8192,
            "gpt-4-0613": 8192,
            "gpt-4-32k": 32768,
            "gpt-4o": 16384,
            "gpt-4.1": 30000,
            "gpt-5.2": 30000,
        }
        # TODO: The 'openai.api_base' option isn't read in the client API. You will need to pass it when you instantiate the client, e.g. 'OpenAI(api_base="https://sailaoda.cn/v1")'
        # openai.api_base = "https://sailaoda.cn/v1"
        num_max_token = num_max_token_map[self.model_type.value]
        num_max_completion_tokens = num_max_token - num_prompt_tokens

        if self.model_type.value == "gpt-5.2":
            resp_obj = client.responses.create(
                model=self.model_type.value,
                input=kwargs["messages"],
                reasoning={"effort": "none"},
                text={"verbosity": "low"},
                max_output_tokens=num_max_completion_tokens,
            )
            resp_dict = resp_obj.model_dump()
            response = self.responses_to_chatcompletions_dict(resp_dict)

        else:
            chat_cfg = dict(self.model_config_dict)
            chat_cfg["max_tokens"] = num_max_completion_tokens
            chat_cfg.pop("max_output_tokens", None)
            chat_cfg.pop("max_completion_tokens", None)

            resp_obj = client.chat.completions.create(
                *args,
                **kwargs,
                model=self.model_type.value,
                **chat_cfg,
            )
            response = resp_obj.model_dump()

        self._log_usage(response)
        return response


class StubModel(ModelBackend):
    r"""A dummy model used for unit tests."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__()

    def run(self, *args, **kwargs) -> Dict[str, Any]:
        ARBITRARY_STRING = "Lorem Ipsum"

        return dict(
            id="stub_model_id",
            usage=dict(),
            choices=[
                dict(finish_reason="stop",
                     message=dict(content=ARBITRARY_STRING, role="assistant"))
            ],
        )


class ModelFactory:
    r"""Factory of backend models.

    Raises:
        ValueError: in case the provided model type is unknown.
    """

    @staticmethod
    def create(model_type: ModelType, model_config_dict: Dict) -> ModelBackend:
        # default_model_type = ModelType.GPT_3_5_TURBO
        default_model_type = ModelType.GPT_4
        if model_type in {
            ModelType.GPT_3_5_TURBO, ModelType.GPT_4, ModelType.GPT_4_32k, ModelType.GPT_4o, ModelType.GPT_4o1, 
            ModelType.GPT_5o2,
            None
        }:
            model_class = OpenAIModel
        elif model_type == ModelType.STUB:
            model_class = StubModel
        else:
            raise ValueError("Unknown model")

        if model_type is None:
            model_type = default_model_type

        # log_and_print_online("Model Type: {}".format(model_type))
        inst = model_class(model_type, model_config_dict)
        return inst
