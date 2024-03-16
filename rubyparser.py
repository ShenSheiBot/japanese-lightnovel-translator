from utils import parse_gpt_json, has_kana, load_config, extract_ruby_from_epub
from apichat import GoogleChatApp, PoeAPIChatApp
import re
import os
import json
from loguru import logger
import yaml


config = load_config()

with open("translation.yaml", "r") as f:
    translation_config = yaml.load(f, Loader=yaml.FullLoader)    


if __name__ == "__main__":
    epub_path = os.path.join('output', config['CN_TITLE'], 'input.epub')
    rubi = extract_ruby_from_epub(epub_path)
    rubi = {k: v for k, v in rubi.items() if not has_kana(v) and has_kana(k)}
    multi_rubi = {re.sub(r'\s', '', k): v for k, v in rubi.items() if len(v) > 1}

    if not len(multi_rubi) == 0:
        with open('resource/rubi_prompt.txt', 'r', encoding='utf-8') as f:
            ruby_prompt = f.read()
        prompt = ruby_prompt + str(multi_rubi)
        logger.info(f"Prompt: {prompt}")
        for name, model in translation_config.items():
            if 'Gemini' in name:
                api_app = GoogleChatApp(api_key=model['key'], model_name=model['name'])
            elif 'Poe' in name:
                api_app = PoeAPIChatApp(api_key=model['key'], model_name=model['name'])
            else:
                continue
            try: 
                response = api_app.chat(prompt)
                dictionary = parse_gpt_json(response)
                dictionary.update(rubi)
                logger.info(dictionary)
                break
            except Exception as e:
                print(e)
                continue
                
    # Dump the final dictionary to CN_TITLE/names.json
    with open(os.path.join('output', config['CN_TITLE'], 'ruby.json'), 'w', encoding='utf-8') as f:
        json.dump(dictionary, f, ensure_ascii=False, indent=4)
