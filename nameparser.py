from utils import load_config, SqlWrapper
from epubparser import main
import os
from apichat import GoogleChatApp, PoeAPIChatApp
import yaml
from loguru import logger
import json
from p_tqdm import p_map


class KeyboardInterruptError(Exception):
    pass


with open('resource/namedetect_prompt_3.txt', 'r', encoding='utf-8') as f:
    prompt = f.read()

with open("translation.yaml", "r") as f:
    translation_config = yaml.load(f, Loader=yaml.FullLoader)    
    
config = load_config()
logger.remove()
logger.add(f"output/{config['CN_TITLE']}/name.log", colorize=True, level="DEBUG")
buffer = SqlWrapper(os.path.join('output', config['CN_TITLE'], 'name.db'))
                
                
def to_json(s):
    s = s[s.find("["):s.rfind("]") + 1]
    s = s.replace('\'', '"')
    s = s.replace("：", ":")
    if s.strip() == '':
        return []
    try:
        j = json.loads(s)
    except json.decoder.JSONDecodeError:
        logger.critical(f"Unparsable: {s}")
        return None
    if j is None:
        logger.critical(f"Unparsable: {s}")
        return None
    for ele in j:
        if "name" not in ele:
            logger.critical(f"Invalid response: {ele}")
            return None
    return j


def extract(content: str):
    inp = prompt + "\n" + content
    # Already parsed
    if content in buffer:
        return
        
    for name, model in translation_config.items():
        if 'Gemini' in name:
            api_app = GoogleChatApp(api_key=model['key'], model_name=model['name'])
        elif 'Poe' in name:
            api_app = PoeAPIChatApp(api_key=model['key'], model_name=model['name'])
        else:
            continue
        
        try:
            response = api_app.chat(inp)
            logger.info(response)
            response_json = to_json(response)
            buffer[content] = str(response_json)
            return
        except KeyboardInterrupt:
            buffer.close()
            raise KeyboardInterruptError()
        except Exception:
            continue


if __name__ == "__main__":
    book_contents = main(os.path.join('output', config['CN_TITLE'], 'input.epub'))
    try:
        p_map(extract, book_contents, num_cpus=8)
    except KeyboardInterrupt:
        print("KeyboardInterrupt caught, terminating processes...")
        buffer.close()
        raise KeyboardInterruptError()
