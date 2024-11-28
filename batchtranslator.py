from utils import load_config, SqlWrapper, gemini_fix
from epubparser import main
import os
import yaml
from loguru import logger
import json
from p_tqdm import p_map
from epubloader import translate
from argparse import ArgumentParser
from typing import List
from prompt import generate_prompt
from apichat import APITranslationFailure


class KeyboardInterruptError(Exception):
    pass


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


def translate_wrapper(cn_title: str, content: str, context: List[dict] = None) -> str:
    logger.remove()
    logger.add(f"output/{cn_title}/info.log", colorize=True, level="DEBUG")
    
    buffer = SqlWrapper(os.path.join('output', cn_title, 'buffer.db'))
    # Already translated
    if (
        content in buffer
    ):
        return
    try:
        cn_text = translate(content, context=context)
    except UnboundLocalError:
        cn_text = translate(content, context=None)
    except APITranslationFailure as e:
        logger.critical(f"API translation failed: {e}")
        return
    cn_text = gemini_fix(cn_text)
    buffer[content] = cn_text
    return cn_text


def chapterwise_translate_wrapper(cn_title: str, contents: List[str]):
    # Already translated
    context = None
    for content in contents:
        cn_text = translate_wrapper(cn_title, content, context=context)
        context = [
            {"role": "user", "content": generate_prompt(content, mode="sakura")},
            {"role": "bot", "content": cn_text},
        ]


if __name__ == "__main__":
    # Option chapterwise
    with open('resource/namedetect_prompt_3.txt', 'r', encoding='utf-8') as f:
        prompt = f.read()

    with open("translation.yaml", "r") as f:
        translation_config = yaml.load(f, Loader=yaml.FullLoader)    

    config = load_config()

    parser = ArgumentParser()
    parser.add_argument("--independent", action="store_true")
    parser.add_argument("--cn-title", type=str)
    parser.add_argument("--jp-title", type=str)
    
    args = parser.parse_args()
    if args.cn_title:
        config['CN_TITLE'] = args.cn_title
    if args.jp_title:
        config['JP_TITLE'] = args.jp_title
    
    buffer = SqlWrapper(os.path.join('output', config['CN_TITLE'], 'buffer.db'))
    update_buffer = SqlWrapper(os.path.join('output', config['CN_TITLE'], 'update_buffer.db'))
        
    if args.independent:
        book_contents = main(os.path.join('output', config['CN_TITLE'], 'input.epub'))
        cn_title = config['CN_TITLE']
        p_map(lambda x, t=cn_title: translate_wrapper(t, x), book_contents, num_cpus=config['NUM_PROCS'])
    else:
        book_contents = main(os.path.join('output', config['CN_TITLE'], 'input.epub'), chapterwise=True)
        book_contents = list(book_contents.values())
        cn_title = config['CN_TITLE']
        p_map(lambda x, t=cn_title: chapterwise_translate_wrapper(t, x), book_contents, num_cpus=config['NUM_PROCS'])
