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


def partition_json(input_json, max_length):
    # Convert the input JSON string to a Python dictionary
    data = json.loads(input_json)
    
    # Initialize variables
    partitions = []
    current_partition = {}
    current_length = 2  # Accounts for the curly braces at the start and end of the JSON
    
    # Iterate over key-value pairs in the original dictionary
    for key, value in data.items():
        # Serialize the current key-value pair to check its length
        item_str = json.dumps({key: value})
        
        # Check if adding this item to the current partition would exceed the max length
        if current_length + len(item_str) - 1 > max_length:  # -1 accounts for the extra curly brace
            # If so, start a new partition
            partitions.append(current_partition)
            current_partition = {key: value}
            current_length = len(item_str)
        else:
            # Otherwise, add the item to the current partition
            current_partition[key] = value
            current_length += len(item_str) - 1  # -1 accounts for the comma that's not needed for the first item
    
    # Add the last partition if it has any items
    if current_partition:
        partitions.append(current_partition)
    
    # Convert the partitions back to JSON strings
    partition_strings = [json.dumps(partition, ensure_ascii=False) for partition in partitions]
    
    return partition_strings


if __name__ == "__main__":
    epub_path = os.path.join('output', config['CN_TITLE'], 'input.epub')
    rubi = extract_ruby_from_epub(epub_path)
    rubi = {k: v for k, v in rubi.items() if not has_kana(v) and has_kana(k)}
    multi_rubi = {re.sub(r'\s', '', k): v for k, v in rubi.items() if len(v) > 1}

    dictionary = {}
    if not len(multi_rubi) == 0:
        with open('resource/rubi_prompt.txt', 'r', encoding='utf-8') as f:
            ruby_prompt = f.read()

        multi_rubies = partition_json(json.dumps(multi_rubi, ensure_ascii=False), 2000)
        for multi_rubi in multi_rubies:
            prompt = ruby_prompt + multi_rubi
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
                    result = parse_gpt_json(response)
                    dictionary.update(result)
                    logger.info(result)
                    break
                except Exception as e:
                    print(e)
                    continue

    dictionary.update(rubi)            
    logger.info(dictionary)
    
    # Load exclusions from resource/exclusions.txt
    with open('resource/exclusions.txt', 'r', encoding='utf-8') as f:
        exclusions = f.read().splitlines()
    
    for exclusion in exclusions:
        if exclusion in dictionary:
            del dictionary[exclusion]
    # Dump the final dictionary to CN_TITLE/names.json
    with open(os.path.join('output', config['CN_TITLE'], 'ruby.json'), 'w', encoding='utf-8') as f:
        json.dump(dictionary, f, ensure_ascii=False, indent=4)
