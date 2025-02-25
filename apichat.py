from openai import OpenAI
import openai
import google.generativeai as genai
import yaml
import time
import asyncio
import fastapi_poe as fp
from fastapi_poe import BotError
from anthropic import Anthropic
import random


last_chat_time = None


class APITranslationFailure(Exception):
    def __init__(self, message="API connection failed after retries.", *args):
        super().__init__(message, *args)


class APIChatApp:
    def __init__(self, api_key, model_name, temperature):
        self.api_key = api_key
        self.model_name = model_name
        self.messages = [{"role": "system", "content": "API_PROMPT"}]  # Replace API_PROMPT with actual prompt if needed
        self.response = None
        self.temperature = temperature

    def chat(self, message):
        raise NotImplementedError("Subclasses must implement this method")


class OpenAIChatApp(APIChatApp):
    def __init__(self, api_key, model_name, temperature=0.7, endpoint="https://api.openai.com/v1"):
        super().__init__(api_key, model_name, temperature)
        self.client = OpenAI(
            api_key=api_key,
            base_url=endpoint
        )
        
        self.messages = [
            {
                "role": "system", 
                "content": "你是一个轻小说翻译模型，可以流畅通顺地以日本轻小说的风格将日文翻译成简体中文，并联系上下文正确使用人称代词，不擅自添加原文中没有的代词。"
            }
        ]

    def chat(self, message):
        self.messages.append(
            {
                "role": "user", 
                "content": message
            }
        )
        try:
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=self.messages,
                temperature=self.temperature,
                stop=["<|im_end|>"],
                frequency_penalty=0.5
            )
            self.messages = [{"role": "assistant", "content": response.choices[0].message.content}]
            self.response = response
            return response.choices[0].message.content
        except openai.APIError as e:
            raise APITranslationFailure(f"OpenAI API connection failed: {str(e)}")


class GoogleChatApp(APIChatApp):
    def __init__(self, api_key, model_name, temperature=0.2):
        super().__init__(api_key, model_name, temperature)
        genai.configure(api_key=self.api_key)
        self.model = genai.GenerativeModel(self.model_name)

    def chat(self, message):
        global last_chat_time
        
        if last_chat_time is not None:
            elapsed_time = time.time() - last_chat_time
            if elapsed_time < 1:
                time_to_wait = 1 - elapsed_time
                time.sleep(time_to_wait)
        last_chat_time = time.time()
            
        self.messages.append({"role": "user", "content": message})
        try:
            prompt = "".join([m["content"] for m in self.messages])
            response = self.model.generate_content(
                prompt,
                safety_settings=[
                    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
                    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
                    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
                    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
                ],
                generation_config={"temperature": self.temperature, "max_output_tokens": 8192}
            )
            if 'block_reason' in response.prompt_feedback:
                print(vars(response))
                raise APITranslationFailure("Content generation blocked due to safety settings.")
            
            try:
                rtn = response.text
            except Exception:
                for candidate in response.candidates:
                    rtn = "\n".join([part.text for part in candidate.content.parts])
            self.messages = [{"role": "assistant", "content": rtn}]
            return rtn
        except Exception as e:
            raise APITranslationFailure(f"Google API connection failed: {str(e)}")


class PoeAPIChatApp:
    # Backoff variables
    MAX_BACKOFF_TIME = 20  # Maximum backoff time in seconds
    BASE_BACKOFF_TIME = 5  # Base backoff time in seconds
    _BACKOFF_TIME = BASE_BACKOFF_TIME  # Current backoff time
    
    def __init__(self, api_key, model_name):
        self.api_key = api_key
        self.model_name = model_name
        self.messages = []
        
    def chat(self, message):
        return asyncio.run(self._async_chat(message))
    
    @classmethod
    def get_backoff_time(cls):
        return cls._BACKOFF_TIME
    
    @classmethod
    def update_backoff_time(cls):
        cls._BACKOFF_TIME = min(cls._BACKOFF_TIME * 2, cls.MAX_BACKOFF_TIME)
        
    @classmethod
    def reset_backoff_time(cls):
        cls._BACKOFF_TIME = cls.BASE_BACKOFF_TIME

    async def _async_chat(self, message):
        self.messages.append({"role": "user", "content": message})
        final_message = ""
        try:
            async for partial in fp.get_bot_response(messages=self.messages, bot_name=self.model_name, 
                                                     api_key=self.api_key):
                final_message += partial.text
        except BotError as e:
            if "rate limit" in str(e):
                # Exponential backoff
                backoff_time = self.get_backoff_time()
                print(f"Rate limit hit, backing off for {backoff_time} seconds.")
                await asyncio.sleep(backoff_time + random.uniform(0, 1))  # Add some jitter
                self.update_backoff_time()
            elif "nternal" in str(e):
                print(f"Internal server error.")
                self.reset_backoff_time()
            else:
                print(f"API error: {str(e)}")
                self.reset_backoff_time()
            raise APITranslationFailure(f"Poe API connection failed: {str(e)}")
        return final_message


class AnthropicChatApp(APIChatApp):
    def __init__(self, api_key, model_name, temperature=1.0):
        super().__init__(api_key, model_name, temperature)
        self.client = Anthropic(api_key=self.api_key)
        self.messages = []

    def chat(self, message):
        self.messages.append({"role": "user", "content": message})
        try:
            response = self.client.messages.create(
                model=self.model_name,
                messages=self.messages,
                max_tokens=1000,
                temperature=self.temperature
            )
            assistant_message = response.content[0].text
            self.messages.append({"role": "assistant", "content": assistant_message})
            return assistant_message
        except Exception as e:
            raise APITranslationFailure(f"Anthropic API connection failed: {str(e)}")


if __name__ == "__main__":
    # Example usage:
    with open("translation.yaml", "r") as f:
        translation_config = yaml.load(f, Loader=yaml.FullLoader)
        
    sakura_chat = OpenAIChatApp(
        api_key=translation_config['Sakura-OpenAI-api']['key'], 
        endpoint=translation_config['Sakura-OpenAI-api']['endpoint'],
        model_name='llama3-405b'
    )

    prompt = f"""掌にのる小さな模型ほどの黒馬がこちらへ向って眼球を斜めに動かしながら眼前を過ぎゆくのを認めた私は、ちょうど五寸ほど前方の空間に浮んだ黒馬と真直ぐに眼と眼を見合わせたが、そのとき、灼熱する何かが烈しく私を打つたのは、恐らくこのような種類の生物に接する機会は生涯あるまいと思われるほど永劫に医やされざる絶望と深い悲哀の混合した中の限りない谛念に充たされた、限りない穏和な眼の光かそこにあったからである。私は思わず手を差し伸ばした。"""  # noqa
    print(sakura_chat.chat(prompt))
