import collections
from html import unescape
import logging
import os
import re
import time
from typing import List
from xml.etree import ElementTree
from openai import OpenAI
from urllib.parse import urlparse

from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api.formatters import SRTFormatter

import tiktoken
from exceptions import *

logger = logging.getLogger('bot.summarizer')

PROMPT_RU = "Это транскрипция видео в формате SRT. Напиши главные тезисы взятые из текста и поставь временную метку начала тезиса"
# PROMPT_RU = "Напиши главные тезисы из текста."
FINAL_PROMPT_RU = "Пронумеруй каждый тезис заново."
PROMPT_EN = "This is a transcript in SRT format. Summarize main points from the text and add the timestamps for each point."
FINAL_PROMPT_EN = "Renumerate each point again."

PRICE = {'gpt-3.5-turbo': 0.0005, 'gpt-4o': 0.005, 'gpt-4o-mini': 0.00015, 'deepseek-chat': 0.00007}


def get_youtube_url(text:str) -> str:
   """Find a YouTube link in the text and pick up first"""
   urls = re.findall(r'(https?://[^\s]+)', text)
   for url in urls:
      o = urlparse(url)
      if 'youtu' in o.netloc:
         return url
      else:
         return False

def get_youtube_video_id(url:str) -> str:
   """Get video ID from YouTube URL"""
   params = re.search(r'(?:^|\W)(?:youtube(?:-nocookie)?\.com/(?:.*[?&]v=|v/|e(?:mbed)?/|[^/]+/.+/)|youtu\.be/)([\w-]+)', url)
   if params:
      return params.group(1)
   else:
      return False

def calculate_cost(tokens: List[int], chat_model: str) -> int:
   """Cost calculation in rub"""   
   size = len(tokens) / 1000
   cost = size * PRICE[chat_model]
   return int(cost * 100 * 1.1) + 1

def xml_caption_to_text(xml_captions: str) -> str:
   """Convert xml caption tracks to plain text."""
   segments = []
   root = ElementTree.fromstring(xml_captions)
   for child in list(root):
      text = child.text or ""
      caption = unescape(text.replace("\n", " ").replace("  ", " "),)
      segments.append(caption)
   return "\n".join(segments).strip()


class Summarizer:
   """Main summarizer logic."""

   def __init__(self, chat_model: str='deepseek-chat', base_url: str='https://api.deepseek.com', model_token_limit: int=64000, youtube_api_proxies: dict[str, str]=None) -> None:
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
      self.youtube_api_proxies = youtube_api_proxies
      self.max_tokens = 50000
      self.model_token_limit = model_token_limit
      self.tokenizer = tiktoken.encoding_for_model('gpt-4o')
      self.seen = collections.defaultdict(dict)

   def split_to_chunks(self, text_data: str, prompt: str) -> List[str]:
      """
      Long encoded text won't fit the model, so we need to split based on max token limit
      that model supports
      """
      token_integers = self.tokenizer.encode(text_data)
      chunk_size = self.max_tokens - len(self.tokenizer.encode(prompt))
      chunks = [
         token_integers[i : i + chunk_size]
         for i in range(0, len(token_integers), chunk_size)
      ]
      chunks = [self.tokenizer.decode(chunk) for chunk in chunks]
      return chunks

   def summarize(self, context: str, prompt: str, final_prompt: str, cost_estimate: bool=True) -> str:
      """
      Split long input to chunks
      Generate summary for individual chunk
      Renumerate all output bullet points with the final prompt
      """
      chunks = self.split_to_chunks(context, prompt)

      cost = calculate_cost(self.tokenizer.encode(context), self.chat_model)
      logger.info(f"Cost is {cost}")
      if cost > 10:
         raise TooExpensiveException(cost)
      cost_line = f"\n\nС вас {cost} руб."

      responses = []
      for i, chunk in enumerate(chunks):
         logger.info(f"Process chunk {i} out of {len(chunks)}")
         completion = self.client.chat.completions.create(
            model=self.chat_model,
            messages=[
               {"role": "system", "content": chunk},
               {"role": "user", "content": prompt}
            ]
         )
         response = completion.choices[0].message.content.strip()
         responses.append(response)

      logger.debug(responses)
      
      if final_prompt and len(responses) > 1:
         response = self.client.chat.completions.create(
            model=self.chat_model,
            messages=[
               {"role": "system", "content": "\n".join(responses)},
               {"role": "user", "content": final_prompt}
            ]
         )
         final_response = response.choices[0].message.content.strip()
      else:
         final_response = "\n".join(responses)

      if cost_estimate:
         final_response += cost_line

      logger.debug(final_response)
      return final_response

   def get_youtube_summary(self, chat_id: int, text: str, clarify: str=None) -> str:
      """
      Extract captions from a YouTube video for [ru,en] or autogenerated [a.ru,a.en]
      Strip the timestamps
      Pass to a model backend
      """
      logger.debug(text)

      url = get_youtube_url(text)
      if not url:
         raise NotYoutubeUrlException(f"Url {url} is not a YouTube url")
      
      video_id = get_youtube_video_id(url)
      if not video_id:
         raise NotYoutubeUrlException(f"Url {url} is not a YouTube url as it doesn't contain video ID")
      
      transcript_list = YouTubeTranscriptApi.list_transcripts(video_id, proxies=self.youtube_api_proxies)
      transcript = transcript_list.find_transcript(['ru', 'en'])
      
      if chat_id in self.seen and not clarify:
         if video_id in self.seen[chat_id]:
            raise AlreadySeenException(f"Already seen it previously")
      
      try:
         captions = None
         if transcript.language_code == 'ru':
            captions = YouTubeTranscriptApi.get_transcript(video_id, languages=['ru'], proxies=self.youtube_api_proxies)
            captions_srt = SRTFormatter().format_transcript(captions)
            if not clarify:
               prompt = PROMPT_RU
               # final_prompt = FINAL_PROMPT_RU
               final_prompt = None
            else:
               prompt = f"Это транскрипция к видео в формате SRT. Проанализируй текст и перескажи что говорится про \"{clarify}\". Покажи временные метки где об этом говорится. Если об этом ничего нет напиши 'NOT_FOUND'"
               final_prompt = None
         elif transcript.language_code == 'en':
            captions = YouTubeTranscriptApi.get_transcript(video_id, languages=['en'], proxies=self.youtube_api_proxies)
            captions_srt = SRTFormatter().format_transcript(captions)
            if not clarify:
               prompt = PROMPT_EN
               final_prompt = None
            else:
               prompt = f"This is transcript from video in SRT format. Show the timestamp where it says about {clarify}. If there is nothing about it in the video write 'NOT_FOUND'"
               final_prompt = None
         if not captions_srt:
            raise NoCaptionsException
         
         text = captions_srt

      except Exception as e:
         logger.error(e)
         raise NoCaptionsException(f"Cannot get captions for video{url}")

      reply = self.summarize(text, prompt, final_prompt)
      if not clarify:
         self.seen[chat_id][video_id] = time.time()
      return reply


if __name__ == '__main__':
   summarizer = Summarizer()
   reply = summarizer.get_youtube_summary("https://youtu.be/DsUxuz_Rt8g")
   logger.info(reply)


