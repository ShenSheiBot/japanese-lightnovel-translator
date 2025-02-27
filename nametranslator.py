from utils import (
    load_config,
    SqlWrapper,
    has_kana,
    has_chinese,
    find_example_sentences,
    contains_russian_characters,
    toggle_kana
)
import yaml
import os
import json
from apichat import GoogleChatApp, PoeAPIChatApp, OpenAIChatApp, AnthropicChatApp
from loguru import logger
import re
from epubparser import main
import argparse
from pathlib import Path
from typing import Dict


def load_previous_translations(previous_book_paths: list) -> Dict:
    """
    Load translations from multiple previous books.
    Later books override translations from earlier books if there are conflicts.
    """
    previous_translations = {}
    
    for book_path in previous_book_paths:
        names_path = Path(book_path) / 'names.json'
        if not names_path.exists():
            logger.warning(f"No names.json found in {book_path}")
            continue
            
        with open(names_path, 'r', encoding='utf-8') as f:
            book_translations = json.loads(f.read())
            
        # Log any overrides for tracking
        for name, translation in book_translations.items():
            if name in previous_translations:
                old_trans = previous_translations[name]['cn_name']
                new_trans = translation['cn_name']
                if old_trans != new_trans:
                    logger.info(f"Overriding translation for {name}: {old_trans} -> {new_trans}")
                    
        previous_translations.update(book_translations)
        logger.info(f"Loaded {len(book_translations)} translations from {book_path}")
        
    return previous_translations


with open("config/nametranslator.yaml", "r", encoding="utf-8") as f:
    translation_config = yaml.load(f, Loader=yaml.FullLoader)    

config = load_config()
rubies = set()

with open("resource/nametranslate_prompt.txt", "r", encoding="utf-8") as f:
    prompt = f.read()
    prompt_user, prompt_bot, sakura_prompt_bot = prompt.split("\n---\n")


def generate_msg(to_query, example_sentences):
    json_msg = ""
    for name in to_query:
        json_msg += name
        tags = [tag for tag in names[name]['info'] if tag != "人名" and tag != "術語"]
        tags.sort(key=lambda x: names[name]['info'][x]['count'], reverse=True)
        tags = tags[:5]
        
        if tags:
            json_msg += (
                "：" + "，".join(tags) + "，"
            )
        else:
            json_msg = json_msg + "："
        if "example sentence" not in example_sentences[name]:
            json_msg = json_msg.rstrip() + " 例句：" + example_sentences[name] + f",<{name}>\n"
        else:
            json_msg = json_msg[:-2] + f",<{name}>\n"
    return """翻译以下日文文本为中文：\n""" + json_msg


def add_translated(msg, names_original, names_processed):
    # Use regex to find all <name>
    names = re.findall(r'<(.*?)>', msg)
    for name in names:
        if name in names_original:
            aliases = names_original[name]['alias']
            related_translations = []
            for alias in aliases:
                if alias in names_processed:
                    related_translations.append(
                        f"{names_processed[alias]['jp_name']} -> {names_processed[alias]['cn_name']}"
                    )
            if related_translations:
                msg = msg.replace(
                    f"<{name}>",
                    f"相关翻译：" + "，".join(related_translations)
                )
            else:
                msg = msg.replace(f"<{name}>", "")
    return msg


def to_json(s, jp_names):
    s = s.replace(":", "：")
    lines = s.strip().split("\n")
    lines = [line for line in lines if "：" in line and len(line.split("：")[1].strip()) > 0]
    assert ['：' in line for line in lines], f"Invalid response: {lines}"
    j = [line.split("：")[0].strip() for line in lines]
    rtn = {}
    if len(jp_names) == 1:
        j = [j[0]]
    assert len(j) == len(jp_names), f"Result length mismatch: {len(j)} {len(jp_names)}"
    for jp_name, cn_name in zip(jp_names, j):
        cn_name = cn_name.replace("ちゃん", "酱")
        res = re.sub(r'[\u3040-\u309F\u30A0-\u30FA\u30FC-\u30FF]', '之', cn_name)
        if res.count("之") > 2:
            logger.critical(f"Too many Kana: {jp_name} {cn_name}")
            return None
        else:
            cn_name = res
        cn_name = re.sub(r'(.)々', r'\1\1', cn_name)
        if (
            "・" not in jp_name
            and "·" not in jp_name
            and "＝" not in jp_name
            and "=" not in jp_name
        ) and ("・" in cn_name or "·" in cn_name):
            rtn[jp_name] = cn_name.replace("・", "").replace("·", "")
        # if "・" in jp_name and "・" not in cn_name and "·" not in cn_name:
        #     logger.critical(f"Missing ・: {jp_name} {cn_name}")
        #     return None, j
        rtn[jp_name] = cn_name.replace("＝", "・").replace("=", "・").replace("·", "・")
    return rtn


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--previous-books",
        nargs="+",
        help="Paths to previous book output folders containing names.json",
    )
    args = parser.parse_args()

    with open(os.path.join('output', config['CN_TITLE'], 'names_raw.json'), encoding='utf-8') as f:
        names = json.loads(f.read())

    logger.add(f"output/{config['CN_TITLE']}/name_translate.log", colorize=True, level="DEBUG")

    # Load previous translations if provided
    previous_translations = {}
    if args.previous_books:
        previous_translations = load_previous_translations(args.previous_books)
        logger.info(f"Loaded total of {len(previous_translations)} previous translations")

    visited = set()
    queue = []
    to_query = []
    msgs = []
    total_names = 0

    book = main(os.path.join('output', config['CN_TITLE'], 'input.epub'))
    example_sentences = find_example_sentences(list(names.keys()), book)

    for entry in names:
        if entry not in visited:
            visited.add(entry)
            
            # Skip one char names
            if len(entry) <= 1:
                continue
            
            # Skip names without kana and without gender
            if not has_kana(entry) and "男性" not in names[entry]["info"] and "女性" not in names[entry]["info"]:
                continue
            
            to_query.append(entry)
            queue.append(entry)

            while queue:
                current = queue.pop(0)
                for neighbor in names[current]['alias']:
                    if neighbor not in visited:
                        visited.add(neighbor)
                        to_query.append(neighbor)
                        queue.append(neighbor)

    to_querys = [to_query[i:i + 1] for i in range(0, len(to_query), 1)]
    for to_query in to_querys:
        msgs.append(generate_msg(to_query, example_sentences))
        total_names += len(to_query)

    with SqlWrapper(os.path.join('output', config['CN_TITLE'], 'name_translate.db')) as buffer:
        # Remove all counts related information
        names_processed = {}
        api_app = None
        previous_conservation = [
            {
                "role": "user",
                "content": prompt_user
            },
            {
                "role": "assistant",
                "content": sakura_prompt_bot
            }
        ]

        for msg in msgs:
            name_list = re.findall(r'<(.*?)>', msg)
            to_del = []
            for jp_name in name_list:
                if jp_name not in names:
                    to_del.append(jp_name)
            for jp_name in to_del:
                name_list.remove(jp_name)

            if msg in buffer and buffer[msg] != "[]":
                try:
                    response_json = yaml.load(buffer[msg], Loader=yaml.FullLoader)
                    if type(response_json) is tuple:
                        response_json = response_json[1]
                    elif response_json is None:
                        raise Exception
                except Exception as e:
                    logger.critical(e)
                    raise
            else:
                original_msg = msg
                relevant_entries = names_processed.copy()
                relevant_entries.update(previous_translations)
                msg = add_translated(msg, names, relevant_entries)
                flag = True
                for jp_name, model in translation_config.items():
                    if 'Gemini' in jp_name:
                        api_app = GoogleChatApp(api_key=model['key'], model_name=model['name'])
                        api_app.messages = previous_conservation
                        if previous_conservation[-1]['role'] == 'assistant':
                            previous_conservation[-1]['role'] = 'bot'
                    elif 'Poe' in jp_name:
                        api_app = PoeAPIChatApp(api_key=model['key'], model_name=model['name'])
                        api_app.messages = previous_conservation
                        if previous_conservation[-1]['role'] == 'assistant':
                            previous_conservation[-1]['role'] = 'bot'
                    elif 'Claude' in jp_name:
                        api_app = AnthropicChatApp(
                            api_key=model["key"],
                            model_name=model["name"],
                        )
                        api_app.messages = previous_conservation
                    elif 'Sakura' in jp_name:
                        api_app = OpenAIChatApp(
                            api_key=model["key"],
                            model_name=model["name"],
                            endpoint=model["endpoint"],
                        )
                        api_app.messages = previous_conservation
                    elif 'OpenAI' in jp_name:
                        api_app = OpenAIChatApp(
                            api_key=model["key"],
                            model_name=model["name"],
                            endpoint=model["endpoint"],
                        )
                        api_app.messages = previous_conservation
                    else:
                        continue

                    retry_count = model['retry_count']

                    while flag and retry_count > 0:
                        try:
                            logger.debug("\n" + msg)
                            response = api_app.chat(msg)
                            logger.info("\n" + response)
                            result = to_json(response, name_list)
                            logger.success("\n" + json.dumps(result, ensure_ascii=False, indent=4))
                            if type(result) is tuple:
                                response_json = result[1]
                                raise Exception
                            elif result is None:
                                raise Exception
                            else:
                                assert len(result) == len(
                                    name_list
                                ), f"Result length mismatch: {len(result)} {len(name_list)}"
                                response_json = result
                            buffer[original_msg] = str(response_json)
                            previous_conservation = [
                                {
                                    "role": "user",
                                    "content": prompt_user
                                },
                                {
                                    "role": "assistant",
                                    "content": sakura_prompt_bot
                                },
                                {
                                    "role": "user",
                                    "content": msg
                                },
                                {
                                    "role": "assistant",
                                    "content": response
                                }
                            ]
                            flag = False
                            break
                        except Exception:
                            import sys
                            exception = sys.exc_info()
                            logger.opt(exception=exception).error("Logging exception traceback")
                            retry_count -= 1
                            continue

            for jp_name, (_, cn_name) in zip(name_list, response_json.items()):
                info = list(names[jp_name]["info"].keys())
                for tag in info:
                    if contains_russian_characters(tag):
                        info.remove(tag)
                if not has_kana(jp_name) and not has_chinese(jp_name):
                    cn_name = jp_name
                names_processed[jp_name] = {
                    "jp_name": jp_name,
                    "cn_name": cn_name,
                    "alias": names[jp_name]["alias"],
                    "info": info
                }

        items_to_process = list(names_processed.items())
        for jp_name, cn_name in items_to_process:
            info = cn_name['info']
            cn_name = cn_name['cn_name']
            if 'ruby' in names[jp_name]:
                for ruby in names[jp_name]['ruby']:
                    if not has_kana(ruby) or not has_chinese(jp_name):
                        continue
                    rubies.add(ruby)
                    if ruby in names_processed:
                        logger.critical(f"Ruby conflict: {ruby} {names_processed[ruby]['cn_name']} -> {cn_name}")
                    else:
                        names_processed[ruby] = {
                            "jp_name": ruby,
                            "cn_name": cn_name,
                            "alias": names[jp_name]["alias"],
                            "info": info
                        }

        for jp_name, cn_name in names_processed.items():
            cn_name = cn_name['cn_name']
            if not has_kana(jp_name) and not has_kana(cn_name) and has_chinese(jp_name) and has_chinese(cn_name):
                if len(cn_name) != len(jp_name):
                    logger.critical(f"Length mismatch: {jp_name} {cn_name}")
            if toggle_kana(jp_name) in names_processed and names_processed[toggle_kana(jp_name)]['cn_name'] != cn_name:
                if jp_name in rubies:
                    continue
                if toggle_kana(jp_name) in rubies:
                    names_processed[jp_name]['cn_name'] = names_processed[toggle_kana(jp_name)]['cn_name']
                    logger.info(f"Toggle corrected: {jp_name}: {cn_name} -> {names_processed[jp_name]['cn_name']}")
                else:
                    logger.critical(f"Toggle mismatch: {jp_name} {cn_name}")

        print(total_names)
        print(len(names_processed))
        with open(os.path.join('output', config['CN_TITLE'], 'names.json'), "w", encoding="utf-8") as f:
            f.write(json.dumps(names_processed, ensure_ascii=False, indent=4))
