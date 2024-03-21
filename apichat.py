from openai import OpenAI
import openai
import google.generativeai as genai
import yaml
import time
import asyncio
import fastapi_poe as fp
import requests
import re
import json


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
        if "gpt" in model_name:
            endpoint = "https://api.openai.com/v1"
        # print(base_url)
        self.client = OpenAI(
            api_key=api_key,
            base_url=endpoint
        )

    def chat(self, message):
        self.messages = [
            {
                "role": "system", 
                "content": "你是一个轻小说翻译模型，可以流畅通顺地以日本轻小说的风格将日文翻译成简体中文，并联系上下文正确使用人称代词，不擅自添加原文中没有的代词。"
            }, 
            {
                "role": "user", 
                "content": message
            }
        ]
        try:
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=self.messages,
                temperature=self.temperature
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
        prompt = "".join([m["content"] for m in self.messages])
        try:
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
            self.messages = [{"role": "assistant", "content": response.text}]
            return response.text
        except Exception as e:
            raise APITranslationFailure(f"Google API connection failed: {str(e)}")


class PoeAPIChatApp:
    def __init__(self, api_key, model_name):
        self.api_key = api_key
        self.model_name = model_name
        self.messages = []
        
    def chat(self, message):
        return asyncio.run(self._async_chat(message))
    
    async def _async_chat(self, message):
        self.messages.append({"role": "user", "content": message})
        final_message = ""
        try:
            async for partial in fp.get_bot_response(messages=self.messages, bot_name=self.model_name, 
                                                     api_key=self.api_key):
                final_message += partial.text
        except Exception as e:
            raise APITranslationFailure(f"Poe API connection failed: {str(e)}")
        return final_message


class BaichuanChatApp:
    def __init__(self, api_key, model_name):
        self.api_key = api_key
        self.model_name = model_name
        self.url = 'https://api.baichuan-ai.com/v1/chat/completions'
        self.headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {self.api_key}'
        }
    
    def chat(self, message, temperature=0.3, top_p=0.85, max_tokens=2048):
        payload = {
            "model": self.model_name,
            "messages": [{
                "role": "user",
                "content": message
            }],
            "temperature": temperature,
            "top_p": top_p,
            "max_tokens": max_tokens,
            "with_search_enhance": False,
            "stream": True
        }

        response = requests.post(self.url, headers=self.headers, data=json.dumps(payload))
        if response.status_code == 200:
            raw_stream_response = response.text
            matches = ''.join(re.findall(r'\"content\":\"(.*?)\"', raw_stream_response, re.DOTALL))
            finish_reason_matches = re.findall(r'\"finish_reason\":\"(.*?)\"', raw_stream_response)
            if not finish_reason_matches or "stop" not in finish_reason_matches:
                err_msg = "\n".join(response.text.split('\n')[-5:])
                raise APITranslationFailure(f"Baichuan API translation terminated: {err_msg}")
            else:
                return matches.replace('\\n', '\n')
        else:
            raise APITranslationFailure(f"Baichuan API connection failed: {response.text}")


if __name__ == "__main__":
    # Example usage:
    with open("translation.yaml", "r") as f:
        translation_config = yaml.load(f, Loader=yaml.FullLoader)
        
    google_chat = GoogleChatApp(
        api_key=translation_config['Gemini-Pro-api']['key'], 
        model_name='gemini-pro'
    )
    poe_chat = PoeAPIChatApp(
        api_key=translation_config['Poe-claude-api']['key'], 
        model_name=translation_config['Poe-claude-api']['name']
    )

    prompt = f"""
    翻译以下日文轻小说为中文。
    ---
    四つん這いの艾莉亚丝の体が小刻みに震え、次の瞬間には股間から透明な飛沫が後ろに向かって飛んだ。

    """
    # print(openai_chat.chat(prompt))
    # print(google_chat.chat(prompt))
    print(poe_chat.chat(prompt))
