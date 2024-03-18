from utils import load_config, SqlWrapper, gemini_fix
from epubparser import main
import os
import yaml
from loguru import logger
import json
from p_tqdm import p_map
from epubloader import translate, post_translate


class KeyboardInterruptError(Exception):
    pass


with open('resource/namedetect_prompt_3.txt', 'r', encoding='utf-8') as f:
    prompt = f.read()

with open("translation.yaml", "r") as f:
    translation_config = yaml.load(f, Loader=yaml.FullLoader)    

config = load_config()
logger.remove()
logger.add(f"output/{config['CN_TITLE']}/info.log", colorize=True, level="DEBUG")
buffer = SqlWrapper(os.path.join('output', config['CN_TITLE'], 'buffer.db'))


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


def translate_wrapper(content: str):
    # Already translated
    if (
        content in buffer
    ):
        return
    cn_text = translate(content)
    cn_text = gemini_fix(cn_text)
    # cn_text = post_translate(cn_text)
    buffer[content] = cn_text


if __name__ == "__main__":
    book_contents = main(os.path.join('output', config['CN_TITLE'], 'input.epub'))
    try:
        p_map(translate_wrapper, book_contents, num_cpus=8)
    except KeyboardInterrupt:
        print("KeyboardInterrupt caught, terminating processes...")
        buffer.close()
        raise KeyboardInterruptError()
