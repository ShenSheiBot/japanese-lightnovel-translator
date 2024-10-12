import json
from utils import load_config, get_appeared_names
from loguru import logger
import os
import re


config = load_config()

if os.path.exists(f"output/{config['CN_TITLE']}/names.json"):
    with open(f"output/{config['CN_TITLE']}/names.json", encoding='utf-8') as f: 
        names = json.loads(f.read())
        names = {k: v for k, v in sorted(names.items(), key=lambda item: len(item[0]), reverse=True)}
        name_convention = names
else:
    name_convention = {}


change_list = set()


if os.path.exists(f"output/{config['CN_TITLE']}/names_updated.json"):
    with open(f"output/{config['CN_TITLE']}/names_updated.json", encoding='utf-8') as f:
        names_updated = json.loads(f.read())
        names_updated = {k: v for k, v in sorted(names_updated.items(), key=lambda item: len(item[0]), reverse=True)}
        for name in names_updated:
            if name not in name_convention:
                change_list.add(name)
            elif name in name_convention and name_convention[name] != names_updated[name]:
                change_list.add(name)
        name_convention = names_updated
        logger.info(f"Changed name conventions: {change_list}")

name_convention_short = {k: (v["cn_name"] if type(v) is dict else v) for k, v in name_convention.items()}
logger.info(f"Loaded name conventions: {name_convention_short}")

soft_name_convention = {
}

name_convention.update(soft_name_convention)


def generate_prompt(text, mode="translation"):
    """
    mode: translation, title_translation, polish, sakura
    """
    if mode == "title_translation":
        prompt = "翻译以下日文轻小说标题为中文。你除了中文翻译不回答任何内容。\n\n"
    elif mode == "translation":
        prompt = "翻译以下日文轻小说章节为中文。我发送日文原文，你除了中文翻译不回答任何内容。"
        "回答形如：\n1 第一章的中文名\n2 第二章的中文名\n\n"
    elif mode == "sakura":
        prompt = "将下面的日文文本根据对应关系和备注翻译成中文：\n"
    else:
        raise ValueError(f"Unknown mode: {mode}")
    appeared_names = get_appeared_names(text, name_convention)

    ## Soft
    if len(appeared_names) > 0:
        if mode != "sakura" and type(list(appeared_names.values())[0]) is dict:
            ppt = "在翻译时，考虑如下的翻译背景：\n"
            for key in appeared_names:
                if key in text:
                    if "人名" in appeared_names[key]['info'] and "組織名" not in appeared_names[key]['info']:
                        if "男性" in appeared_names[key]['info']:
                            ppt += f"【{key}】是男性"
                        elif "女性" in appeared_names[key]['info']:
                            ppt += f"【{key}】是女性"
                        else:
                            ppt += f"【{key}】"
                        tags = [
                            tag
                            for tag in appeared_names[key]["info"]
                            if tag != "人名"
                            and tag != "術語"
                            and tag != "女性"
                            and tag != "男性"
                            and "組織" not in tag
                        ]
                        if len(tags) > 0:
                            ppt += (
                                "，身份有" + "、".join([
                                    tag
                                    for tag in appeared_names[key]["info"]
                                    if tag != "人名" and tag != "術語" and tag != "女性" and tag != "男性"
                                ])
                            )
                        ppt += f"，应翻译为【{appeared_names[key]['cn_name']}】。\n"
                    elif "地名" in appeared_names[key]['info']:
                        ppt += f"【{key}】是地名，应翻译为【{appeared_names[key]['cn_name']}】。\n"
                    elif "組織名" in appeared_names[key]['info']:
                        ppt += f"【{key}】是组织名，应翻译为【{appeared_names[key]['cn_name']}】。\n"
                    else:
                        ppt += f"【{key}】，应翻译为【{appeared_names[key]['cn_name']}】。\n"
            prompt = ppt + '\n' + prompt

        elif mode == "sakura":
            ppt = "根据以下术语表（可以为空）：\n"
            ppt += "\n".join(
                [
                    f"{key}->{value['cn_name']}"
                    for key, value in list(appeared_names.items())[:20]
                    if key in text
                ]
            )
            prompt = ppt + '\n\n\n' + prompt
        else:
            prompt += "在翻译时，尽量不要包含任何英文，遵守如下的日中人名/地名惯例：\n"
            prompt += "\n".join([f"{key} = {value}" for key, value in list(appeared_names.items())[:20] if key in text])

    if mode == "sakura":
        return prompt + text

    ## Hard
    prompt += "\n\n---------------以下是日文原文---------------\n\n"
    if "无法翻译" in text or "无法翻译" in prompt:
        raise

    text = prompt + text
    if "无法翻译" in text or "无法翻译" in prompt:
        raise
    text += "\n\n---------------以下是中文翻译---------------\n\n"

    return text


def sakura_prompt(text, name_convention, mode):
    appeared_names = get_appeared_names(text, name_convention)
    prompt = "将下面的日文文本翻译成中文："
    mapping = ""
    if "soft" in mode and len(appeared_names) != 0:
        prompt = "将下面的日文文本根据上述术语表的对应关系和备注翻译成中文："
        mapping = "根据以下术语表：\n"
        mapping += "\n".join(
            [
                f"{key}->{value['cn_name']}" + (f"\n{value['cn_name']}->{value['cn_name']}" if "cc" in mode else "")
                for key, value in list(appeared_names.items())[:20]
                if key in text
            ]
        )
    if "hard" in mode:
        for key, value in list(appeared_names.items())[:20]:
            text = text.replace(key, value['cn_name'])
    if mapping:
        prompt = mapping + '\n\n' + prompt
    # Remove extra new lines
    text = re.sub(r'\n\n+', '\n---\n', text)
    return prompt + text


if __name__ == "__main__":
    text = """わたし、エルミナは魔術師だ。
それも条件付きなら世界でも指折りの実力を持っている。""" # noqa

    logger.info(generate_prompt(text, mode="sakura"))
