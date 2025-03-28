from collections import defaultdict
import logging
import os

from openai import OpenAI
import tiktoken

from exceptions import *

logger = logging.getLogger('bot.chat')


class Chat:
    """Main free chat logic"""
    def __init__(self, chat_model: str='deepseek-chat', base_url: str='https://api.deepseek.com', model_token_limit: int=64000) -> None:
        """Construct a :class:`Summarizer <Summarizer>`.

        :param chat_model:
            Type of the backend model to use
        :param model_token_limit:
            Max token limit that backend model supports
        """
        self.base_url = base_url
        self.chat_model = chat_model
        api_key = os.environ.get('OPENAI_API_KEY', None)
        if not api_key:
            raise Exception("API key is not set in the environment variable OPENAI_API_KEY") 
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.max_tokens = 50000
        self.model_token_limit = model_token_limit
        self.tokenizer = tiktoken.encoding_for_model('gpt-4o')
        self.conversation = defaultdict(dict)
    
    def free_chat(self, message: str, chat_id:str, message_id: int, reply_id: int=None) -> str:
        """
        Calculate the length of the conversation in number of tokens
        Process all messages if the request fits the model
        """
        request = {"role": "user", "content": message}
        conversation = self.conversation[chat_id]
        conversation[message_id] = {"request": request, "reply_id": reply_id}
        
        requests = [request]
        while reply_id in conversation:
            requests.append(conversation[reply_id]["request"])
            reply_id = conversation[reply_id]["reply_id"]

        concatenated_messages = " ".join(r["content"] for r in requests)
        tokens = self.tokenizer.encode(concatenated_messages)
        logger.info(f"The length is {len(tokens)}")
        if len(tokens) > self.max_tokens:
            raise TooLongMessageException(len(tokens))
        
        requests.reverse()
        
        response = self.client.chat.completions.create(
            model=self.chat_model,
            messages=requests
        )
        return {"role": response.choices[0].message.role, "content": response.choices[0].message.content.strip()}