from utils import load_config, SqlWrapper, has_kana, has_chinese, postprocessing, find_example_sentences
import yaml
import os
import json
from apichat import GoogleChatApp, PoeAPIChatApp
from loguru import logger
import re
from epubparser import main


with open("translation.yaml", "r", encoding="utf-8") as f:
    translation_config = yaml.load(f, Loader=yaml.FullLoader)    

config = load_config()

with open("resource/nametranslate_prompt.txt", "r", encoding="utf-8") as f:
    prompt = f.read()


def generate_msg(to_query, example_sentences):
    json_msg = "{\n"
    for name in to_query:
        json_msg += f"    \"{name}\": \"\",  "
        tags = [tag for tag in names[name]['info'] if tag != "人名" and tag != "術語"]
        tags.sort(key=lambda x: names[name]['info'][x]['count'], reverse=True)
        tags = tags[:5]
        
        if tags:
            json_msg += (
                "// " + ", ".join(tags) + "， "
            )
        else:
            json_msg += "//"
        if "example sentence" not in example_sentences[name]:
            json_msg = json_msg.rstrip() + " 例句：" + example_sentences[name] + f"，<{name}>\n"
        else:
            json_msg = json_msg[:-2] + f"，<{name}>\n"
            
    json_msg = json_msg + "}"
    msg = prompt.replace("<json>", json_msg)
    return msg


def add_translated(msg, names_original, names_processed):
    # Use regex to find all <name>
    names = re.findall(r'<(.*?)>', msg)
    for name in names:
        aliases = names_original[name]['alias']
        for alias in aliases:
            if alias != name and alias in names_processed:
                msg = msg.replace(
                    f"<{name}>",
                    f"相关翻译：{names_processed[alias]['jp_name']} -> {names_processed[alias]['cn_name']}",
                )
                break
        else:
            msg = msg.replace(f"<{name}>", "")
    return msg


def to_json(s):
    s = s[s.find("{"):s.rfind("}") + 1]
    s = s.replace('\'', '"')
    s = s.replace("：", ":")
    s = re.sub(r',\s*}', '}', s)
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
    for jp_name, cn_name in j.items():
        res = re.sub(r'[\u3040-\u309F\u30A0-\u30FA\u30FC-\u30FF]', '之', cn_name)
        if res.count("之") > 1:
            logger.critical(f"Too many Kana: {jp_name} {cn_name}")
            return None
        else:
            cn_name = res
        cn_name = re.sub(r'(.)々', r'\1\1', cn_name)
                    
        # if not has_kana(jp_name) and not has_kana(cn_name) and has_chinese(jp_name) and has_chinese(cn_name):
        #     cn_name = postprocessing(cn_name)
        if "・" not in jp_name and ("・" in cn_name or "·" in cn_name):
            j[jp_name] = cn_name.replace("・", "").replace("·", "")
        # if "・" in jp_name and "・" not in cn_name and "·" not in cn_name:
        #     logger.critical(f"Missing ・: {jp_name} {cn_name}")
        #     return None, j
    return j


if __name__ == "__main__":
    with open(os.path.join('output', config['CN_TITLE'], 'names_raw.json'), encoding='utf-8') as f:
        names = json.loads(f.read())

    logger.add(f"output/{config['CN_TITLE']}/name_translate.log", colorize=True, level="DEBUG")

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
            to_query.append(entry)
            queue.append(entry)

            while queue:
                current = queue.pop(0)
                for neighbor in names[current]['alias']:
                    if neighbor not in visited:
                        visited.add(neighbor)
                        to_query.append(neighbor)
                        queue.append(neighbor)

                if len(to_query) > 15:
                    total_names += len(to_query)
                    msgs.append(generate_msg(to_query, example_sentences))
                    to_query = []

    total_names += len(to_query)
    msgs.append(generate_msg(to_query, example_sentences))

    with SqlWrapper(os.path.join('output', config['CN_TITLE'], 'name_translate.db')) as buffer:

        # Remove all counts related information
        names_processed = {}

        for msg in msgs:
            retranslate = True
            name_list = re.findall(r'<(.*?)>', msg)

            if msg in buffer and buffer[msg] != "[]":
                try:
                    response_json = to_json(buffer[msg])
                    if type(response_json) is tuple:
                        response_json = response_json[1]
                    elif response_json is None:
                        raise Exception
                    retranslate = False
                except Exception as e:
                    logger.critical(e)
            if retranslate:
                original_msg = msg
                msg = add_translated(msg, names, names_processed)

                # Dryrun: JSON output name -> original name.
                # response = '{' + ', '.join([f'"{name}": "翻{name}译"' for name in name_list]) + '}'
                # response_json = to_json(response)
                flag = True
                for name, model in translation_config.items():
                    if 'Gemini' in name:
                        api_app = GoogleChatApp(api_key=model['key'], model_name=model['name'])
                    # elif 'Poe' in name:
                    #     api_app = PoeAPIChatApp(api_key=model['key'], model_name=model['name'])
                    else:
                        continue

                    retry_count = model['retry_count']

                    while flag and retry_count > 0:
                        try:
                            logger.info(msg)
                            response = api_app.chat(msg)
                            logger.info(response)
                            result = to_json(response)
                            if type(result) is tuple:
                                response_json = result[1]
                                raise Exception
                            elif result is None:
                                raise Exception
                            else:
                                assert len(result) == len(
                                    name_list
                                ), f"Result length mismatch: {len(result)} {len(name_list)}"
                                # new_name_list = set(result.keys())
                                # # Compare the new name list with the old one
                                # if new_name_list != set(name_list):
                                #     logger.critical(f"Name list mismatch: {new_name_list} {name_list}")
                                #     raise Exception
                                response_json = result
                            buffer[original_msg] = str(response_json)
                            flag = False
                            break
                        except Exception:
                            retry_count -= 1
                            continue

            for name, (_, cn_name) in zip(name_list, response_json.items()):
                names_processed[name] = {
                    "jp_name": name,
                    "cn_name": cn_name,
                    "alias": names[name]["alias"],
                    "info": list(names[name]["info"].keys())
                }

        print(total_names)
        print(len(names_processed))
        with open(os.path.join('output', config['CN_TITLE'], 'names.json'), "w", encoding="utf-8") as f:
            f.write(json.dumps(names_processed, ensure_ascii=False, indent=4))
