import os
import re
from abc import ABC, abstractmethod

from camel.agents import RolePlaying
from camel.messages import ChatMessage
from camel.typing import TaskType, ModelType
from MAO.chat_env import ChatEnv
from MAO.statistics import get_info
from MAO.utils import log_and_print_online, log_arguments
import hashlib
from HallucinationTest.check import check 


class Phase(ABC):

    def __init__(self,
                 assistant_role_name,
                 user_role_name,
                 phase_prompt,
                 role_prompts,
                 phase_name,
                 model_type,
                 log_filepath):
        """

        Args:
            assistant_role_name: who receives chat in a phase
            user_role_name: who starts the chat in a phase
            phase_prompt: prompt of this phase
            role_prompts: prompts of all roles
            phase_name: name of this phase
        """
        self.seminar_conclusion = None
        self.assistant_role_name = assistant_role_name
        self.user_role_name = user_role_name
        self.phase_prompt = phase_prompt
        self.phase_env = dict()
        self.phase_name = phase_name
        self.assistant_role_prompt = role_prompts[assistant_role_name]
        self.user_role_prompt = role_prompts[user_role_name]
        self.timeout_seconds = 1.0
        self.max_retries = 3
        self.reflection_prompt = """Here is a conversation between two roles: {conversations} {question}"""
        self.model_type = model_type
        self.log_filepath = log_filepath

    @log_arguments
    def chatting(  
            self,
            chat_env,
            task_prompt: str,
            assistant_role_name: str,
            user_role_name: str,
            phase_prompt: str,
            phase_name: str,
            assistant_role_prompt: str,
            user_role_prompt: str,
            task_type=TaskType.CHATDEV,
            need_reflect=False,
            with_task_specify=False,
            memory=None,
            model_type=ModelType.GPT_3_5_TURBO,
            placeholders=None,
            chat_turn_limit=10
    ) -> str:
        """

        Args:
            chat_env: global chatchain environment TODO: only for employee detection, can be deleted
            task_prompt: user query prompt for building the software
            assistant_role_name: who receives the chat
            user_role_name: who starts the chat
            phase_prompt: prompt of the phase
            phase_name: name of the phase
            assistant_role_prompt: prompt of assistant role
            user_role_prompt: prompt of user role
            task_type: task type
            need_reflect: flag for checking reflection
            with_task_specify: with task specify
            model_type: model type
            placeholders: placeholders for phase environment to generate phase prompt
            chat_turn_limit: turn limits in each chat

        Returns:

        """
        
        if placeholders is None:
            placeholders = {}
        assert 1 <= chat_turn_limit <= 100

        if not chat_env.exist_employee(assistant_role_name):
            raise ValueError(f"{assistant_role_name} not recruited in ChatEnv.")
        if not chat_env.exist_employee(user_role_name):
            raise ValueError(f"{user_role_name} not recruited in ChatEnv.")

        # init role play
        role_play_session = RolePlaying(
            assistant_role_name=assistant_role_name,
            user_role_name=user_role_name,
            assistant_role_prompt=assistant_role_prompt,
            user_role_prompt=user_role_prompt,
            task_prompt=task_prompt,
            task_type=task_type,
            with_task_specify=with_task_specify,
            memory=memory,
            model_type=model_type,
            placeholders=placeholders
        )

        # log_and_print_online("System", role_play_session.assistant_sys_msg)
        # log_and_print_online("System", role_play_session.user_sys_msg)

        # start the chat
        _, input_user_msg = role_play_session.init_chat(None, placeholders, phase_prompt)  
        seminar_conclusion = None  

        # handle chats
        # the purpose of the chatting in one phase is to get a seminar conclusion
        # there are two types of conclusion
        # 1. with "<INFO>" mark
        # 1.1 get seminar conclusion flag (ChatAgent.info) from assistant or user role, which means there exist special "<INFO>" mark in the conversation
        # 1.2 add "<INFO>" to the reflected content of the chat (which may be terminated chat without "<INFO>" mark)
        # 2. without "<INFO>" mark, which means the chat is terminated or normally ended without generating a marked conclusion, and there is no need to reflect
        for i in range(chat_turn_limit):
            # start the chat, we represent the user and send msg to assistant
            # 1. so the input_user_msg should be assistant_role_prompt + phase_prompt
            # 2. then input_user_msg send to LLM and get assistant_response
            # 3. now we represent the assistant and send msg to user, so the input_assistant_msg is user_role_prompt + assistant_response
            # 4. then input_assistant_msg send to LLM and get user_response
            # all above are done in role_play_session.step, which contains two interactions with LLM
            # the first interaction is logged in role_play_session.init_chat
            assistant_response, user_response = role_play_session.step(input_user_msg, chat_turn_limit == 1)  

            conversation_meta = "**" + assistant_role_name + "<->" + user_role_name + " on : " + str(
                phase_name) + ", turn " + str(i) + "**\n\n"  
            #Chief Product Officer: **Chief Product Officer<->Chief Executive Officer on : DemandAnalysis, turn 0**

            # TODO: max_tokens_exceeded errors here
            if isinstance(assistant_response.msg, ChatMessage):
                # we log the second interaction here
                log_and_print_online(role_play_session.assistant_agent.role_name,
                                    conversation_meta + "[" + role_play_session.user_agent.system_message.content + "]\n\n" + assistant_response.msg.content)
                if role_play_session.assistant_agent.info:
                    seminar_conclusion = assistant_response.msg.content
                    break
                if assistant_response.terminated:
                    break

            if isinstance(user_response.msg, ChatMessage):
                # here is the result of the second interaction, which may be used to start the next chat turn
                log_and_print_online(role_play_session.user_agent.role_name,
                                    conversation_meta + "[" + role_play_session.assistant_agent.system_message.content + "]\n\n" + user_response.msg.content)
                if role_play_session.user_agent.info:
                    seminar_conclusion = user_response.msg.content
                    break
                if user_response.terminated:
                    break

            # continue the chat
            if chat_turn_limit > 1 and isinstance(user_response.msg, ChatMessage):
                input_user_msg = user_response.msg
            else:
                break

        # conduct self reflection
        if need_reflect:
            if seminar_conclusion in [None, ""]:
                seminar_conclusion = "<INFO> " + self.self_reflection(task_prompt, role_play_session, phase_name,
                                                                    chat_env)
            if "recruiting" in phase_name:
                if "Yes".lower() not in seminar_conclusion.lower() and "No".lower() not in seminar_conclusion.lower():
                    seminar_conclusion = "<INFO> " + self.self_reflection(task_prompt, role_play_session,
                                                                        phase_name,
                                                                        chat_env)
            elif seminar_conclusion in [None, ""]:
                seminar_conclusion = "<INFO> " + self.self_reflection(task_prompt, role_play_session, phase_name,
                                                                    chat_env)
        else:
            seminar_conclusion = assistant_response.msg.content

        log_and_print_online("**[Seminar Conclusion]**:\n\n {}".format(seminar_conclusion))
        seminar_conclusion = seminar_conclusion.split("<INFO>")[-1]
        return seminar_conclusion
        
    def self_retrieval(self,target_memory,chat_env):
        pass

    def self_reflection(self,
                        task_prompt: str,
                        role_play_session: RolePlaying,
                        phase_name: str,
                        chat_env: ChatEnv) -> str:
        """

        Args:
            task_prompt: user query prompt for building the software
            role_play_session: role play session from the chat phase which needs reflection
            phase_name: name of the chat phase which needs reflection
            chat_env: global chatchain environment

        Returns:
            reflected_content: str, reflected results

        """
        messages = role_play_session.assistant_agent.stored_messages if len(
            role_play_session.assistant_agent.stored_messages) >= len(
            role_play_session.user_agent.stored_messages) else role_play_session.user_agent.stored_messages
        messages = ["{}: {}".format(message.role_name, message.content.replace("\n\n", "\n")) for message in messages]
        messages = "\n\n".join(messages)

        if "recruiting" in phase_name:
            question = """Answer their final discussed conclusion (Yes or No) in the discussion without any other words, e.g., "Yes" """
        elif phase_name == "DemandAnalysis":
            question = """Answer their final product modality in the discussion without any other words, e.g., "PowerPoint" """
        # elif phase_name in [PhaseType.BRAINSTORMING]:
        #     question = """Conclude three most creative and imaginative brainstorm ideas from the whole discussion, in the format: "1) *; 2) *; 3) *; where '*' represents a suggestion." """
        elif phase_name == "LanguageChoose":
            question = """Conclude the programming language being discussed for software development, in the format: "*" where '*' represents a programming language." """
        elif phase_name == "EnvironmentDoc":
            question = """According to the codes and file format listed above, write a requirements.txt file to specify the dependencies or packages required for the project to run properly." """
        else:
            raise ValueError(f"Reflection of phase {phase_name}: Not Assigned.")

        # Reflections actually is a special phase between CEO and counselor
        # They read the whole chatting history of this phase and give refined conclusion of this phase
        reflected_content = \
            self.chatting(chat_env=chat_env,
                          task_prompt=task_prompt,
                          assistant_role_name="Chief Executive Officer",
                          user_role_name="Counselor",
                          phase_prompt=self.reflection_prompt,
                          phase_name="Reflection",
                          assistant_role_prompt=self.ceo_prompt,
                          user_role_prompt=self.counselor_prompt,
                          placeholders={"conversations": messages, "question": question},
                          need_reflect=False,
                          memory=chat_env.memory,
                          chat_turn_limit=1,
                          model_type=self.model_type)

        if "recruiting" in phase_name:
            if "Yes".lower() in reflected_content.lower():
                return "Yes"
            return "No"
        else:
            return reflected_content

    @abstractmethod
    def update_phase_env(self, chat_env):
        """
        update self.phase_env (if needed) using chat_env, then the chatting will use self.phase_env to follow the context and fill placeholders in phase prompt
        must be implemented in customized phase
        the usual format is just like:
        ```
            self.phase_env.update({key:chat_env[key]})
        ```
        Args:
            chat_env: global chat chain environment

        Returns: None

        """
        pass

    @abstractmethod
    def update_chat_env(self, chat_env) -> ChatEnv:
        """
        update chan_env based on the results of self.execute, which is self.seminar_conclusion
        must be implemented in customized phase
        the usual format is just like:
        ```
            chat_env.xxx = some_func_for_postprocess(self.seminar_conclusion)
        ```
        Args:
            chat_env:global chat chain environment

        Returns:
            chat_env: updated global chat chain environment

        """
        pass

    def execute(self, chat_env, chat_turn_limit, need_reflect) -> ChatEnv:
        """
        execute the chatting in this phase
        1. receive information from environment: update the phase environment from global environment
        2. execute the chatting  
        3. change the environment: update the global environment using the conclusion
        Args:
            chat_env: global chat chain environment  
            chat_turn_limit: turn limit in each chat  
            need_reflect: flag for reflection  
        Returns:
            chat_env: updated global chat chain environment using the conclusion from this phase execution
            
        """
        self.update_phase_env(chat_env)
        #讨论结果
        self.seminar_conclusion = \
            self.chatting(chat_env=chat_env,
                          task_prompt=chat_env.env_dict['task_prompt'],
                          need_reflect=need_reflect,
                          assistant_role_name=self.assistant_role_name,
                          user_role_name=self.user_role_name,
                          phase_prompt=self.phase_prompt,
                          phase_name=self.phase_name,
                          assistant_role_prompt=self.assistant_role_prompt,
                          user_role_prompt=self.user_role_prompt,
                          chat_turn_limit=chat_turn_limit,
                          placeholders=self.phase_env,
                          memory=chat_env.memory,
                          model_type=self.model_type)
        chat_env = self.update_chat_env(chat_env)
        return chat_env

class ProcessGeneration(Phase):  
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def remove_empty_lines(self,text):  
        lines = text.split('\n')
        non_empty_lines = [line for line in lines if line.strip()]
        return '\n'.join(non_empty_lines)

    def update_phase_env(self, chat_env):
        self.phase_env.update({"format": chat_env.env_dict['format'] })

    def update_chat_env(self, chat_env) -> ChatEnv:
        if len(self.seminar_conclusion) > 0:
            #chat_env.env_dict['initial_process_text'] = self.seminar_conclusion.split("<INFO>")[-1].lower().replace(".", "").strip()
            start_index = self.seminar_conclusion.rfind('<process>')
            end_index = self.seminar_conclusion.rfind('</process>')
            # chat_env.env_dict['process_name'] =self.seminar_conclusion[:start_index]
            chat_env.env_dict['initial_process_text'] = self.seminar_conclusion[start_index:end_index+len('</process>')]
            # chat_env.env_dict['initial_process_text'] =self.remove_empty_lines(self.seminar_conclusion[start_index:] + self.seminar_conclusion[end_index+len('</process>'):])
            chat_env.env_dict['refinement_process_text'] = chat_env.env_dict['initial_process_text']
        return chat_env

class ActivityRefinement(Phase):  
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def update_phase_env(self, chat_env):
         self.phase_env.update({"task": chat_env.env_dict['task_prompt'],
                                "description":"chat_env.env_dict['task_description']",
                                "refinement_process_text": chat_env.env_dict['refinement_process_text'],
                                "format": chat_env.env_dict['format'], })

    def update_chat_env(self, chat_env) -> ChatEnv:
        if len(self.seminar_conclusion) > 0:
            #chat_env.env_dict['refinement_process_text'] = self.seminar_conclusion.split("<INFO>")[-1].lower().replace(".", "").strip()
            start_index = self.seminar_conclusion.rfind('<process>')
            end_index = self.seminar_conclusion.rfind('</process>')
            chat_env.env_dict['refinement_process_text'] = self.seminar_conclusion[start_index:end_index+len("</process>")]
            # chat_env.env_dict['refinement_process_text'] = self.seminar_conclusion[start_index:] + self.seminar_conclusion[end_index+len('</process>'):]
            chat_env.env_dict['reviewed_process_text'] = chat_env.env_dict['refinement_process_text']

        return chat_env

def extract_suggestions(text): 
    suggestions = re.findall(r'Suggested modification:\s*(.*?)(?:\n|$)', text)
    result = ' \n'.join(suggestions)
    return result

class GiveSuggestion(Phase):  
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def update_phase_env(self, chat_env):
         self.phase_env.update({"task": chat_env.env_dict['task_prompt'],
                                "description":"chat_env.env_dict['task_description']",
                                "reviewed_process_text": chat_env.env_dict['reviewed_process_text'],
                                "suggestions": chat_env.env_dict['suggestions'],
                                "format": chat_env.env_dict['format']  })
    def trim_edges(self,s):  
  
        while s and s[0] == ' ':  
            s = s[1:]  
  
        while s and s[-1] == ' ':  
            s = s[:-1]  
        return s  

    def update_chat_env(self, chat_env) -> ChatEnv:
        if len(self.seminar_conclusion) > 0:
            #chat_env.env_dict['refinement_process_text'] = self.seminar_conclusion.split("<INFO>")[-1].lower().replace(".", "").strip()
            # start_index = self.seminar_conclusion.find('<Branch>')
            # end_index = self.seminar_conclusion.rfind('</Branch>')
            # chat_env.env_dict['suggestions'] = extract_suggestions(self.seminar_conclusion)
            chat_env.env_dict['suggestions'] = self.seminar_conclusion
            if self.trim_edges(chat_env.env_dict['suggestions'])=='There is no error in the process text.':
                chat_env.env_dict['continue_sign_review'] = "0"
            print("continue_sign_review= "+str(chat_env.env_dict['continue_sign_review']))
        return chat_env

class ProcessReview(Phase):  
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def update_phase_env(self, chat_env):
         self.phase_env.update({"task": chat_env.env_dict['task_prompt'],
                                "description":"chat_env.env_dict['task_description']",
                                "reviewed_process_text": chat_env.env_dict['reviewed_process_text'],
                                "format": chat_env.env_dict['format'],
                                "suggestions": chat_env.env_dict['suggestions'] })

    def update_chat_env(self, chat_env) -> ChatEnv:
        if len(self.seminar_conclusion) > 0:
            #chat_env.env_dict['refinement_process_text'] = self.seminar_conclusion.split("<INFO>")[-1].lower().replace(".", "").strip()
            start_index = self.seminar_conclusion.rfind('<process>')
            end_index = self.seminar_conclusion.rfind('</process>')
            chat_env.env_dict['reviewed_process_text'] = self.seminar_conclusion[start_index:end_index+len("</process>")]

        return chat_env

class KnowledgeGraphSuggestion(Phase):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def update_phase_env(self, chat_env):
        # Prepare the environment for the advisor's suggestion phase
        self.phase_env.update({
            "task": chat_env.env_dict['task_prompt'],
            "reviewed_process_text": chat_env.env_dict['reviewed_process_text'],
            "extra_knowledge": chat_env.env_dict.get('extra_knowledge', ''),  # Use .get in case it's not set
            "format": chat_env.env_dict['format'], 
        })

    def update_chat_env(self, chat_env) -> ChatEnv:
        # Store the advisor's suggestion in the environment
        if len(self.seminar_conclusion) > 0:
            chat_env.env_dict['suggestions'] = self.seminar_conclusion
            # Optionally, stop the cycle if the advisor says there are no more suggestions
            if self.seminar_conclusion.strip() == 'There are no further suggestions.':
                chat_env.env_dict['continue_sign_review'] = "0"
        return chat_env


class ProcessDesignerFix(Phase):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def update_phase_env(self, chat_env):
        # Prepare the environment for the designer's fix phase
        self.phase_env.update({
            "task": chat_env.env_dict['task_prompt'],
            "reviewed_process_text": chat_env.env_dict['reviewed_process_text'],
            "suggestions": chat_env.env_dict['suggestions'],
            "format": chat_env.env_dict['format'],
        })

    def update_chat_env(self, chat_env) -> ChatEnv:
        # Update the process text after the designer's fix
        if len(self.seminar_conclusion) > 0:
            start_index = self.seminar_conclusion.rfind('<process>')
            end_index = self.seminar_conclusion.rfind('</process>')
            if start_index != -1 and end_index != -1:
                chat_env.env_dict['reviewed_process_text'] = self.seminar_conclusion[start_index:end_index+len('</process>')]
        return chat_env

class AddAPI(Phase):  
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def update_phase_env(self, chat_env):
         self.phase_env.update({"task": chat_env.env_dict['task_prompt'],
                                "description":"chat_env.env_dict['task_description']",
                                "reviewed_process_text": chat_env.env_dict['reviewed_process_text'],
                                "format": chat_env.env_dict['format'] })

    def update_chat_env(self, chat_env) -> ChatEnv:
        if len(self.seminar_conclusion) > 0:
            #chat_env.env_dict['refinement_process_text'] = self.seminar_conclusion.split("<INFO>")[-1].lower().replace(".", "").strip()
            start_index = self.seminar_conclusion.find('<API>')
            end_index = self.seminar_conclusion.rfind('</API>')
            API= self.seminar_conclusion[start_index+len('<API>'):end_index]
            functionname,text=findfunction(API)  
           
            check_instance=check(chat_env.env_dict['reviewed_process_text'])
            error=check_instance.getError()  
            if len(error)==0: 
                print("len(error)==0!!")
                chat_env.env_dict['continue_sign_test'] = "0"
            print("continue_sign_test= "+str(chat_env.env_dict['continue_sign_test']))
            
            chat_env.env_dict['error_prompt'] = error

        return chat_env

class FormatReview(Phase):  
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def update_phase_env(self, chat_env):
         self.phase_env.update({"task": chat_env.env_dict['task_prompt'],
                                "description":"chat_env.env_dict['task_description']",
                                "reviewed_process_text": chat_env.env_dict['reviewed_process_text'],
                                "error_prompt": chat_env.env_dict['error_prompt'],
                                "format": chat_env.env_dict['format'] })

    def update_chat_env(self, chat_env) -> ChatEnv:
        if len(self.seminar_conclusion) > 0:
            start_index = self.seminar_conclusion.rfind('<process>')
            end_index = self.seminar_conclusion.rfind('</process>')
            chat_env.env_dict['reviewed_process_text'] = self.seminar_conclusion[start_index:end_index+len("</process>")]
            
            # chat_env.env_dict['reviewed_process_text'] = self.seminar_conclusion[start_index:] + self.seminar_conclusion[end_index+len('</process>'):]
        return chat_env

def findfunction(text):
  start_index = text.find('(')
  end_index = text.rfind(')')

  inner_string = text[start_index + 1:end_index]

  outer_string = text[:start_index]
  return outer_string,inner_string
