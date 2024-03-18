import json
from utils import load_config, get_appeared_names
from loguru import logger
import os


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
        prompt = "翻译以下日文轻小说标题为中文。\n\n"
    elif mode == "translation":
        prompt = "翻译以下日文轻小说章节为中文。我发送日文原文，你除了中文翻译不回答任何内容。"
        "回答形如：\n1 第一章的中文名\n2 第二章的中文名\n\n"
    elif mode == "sakura":
        prompt = "将下面的日文文本翻译成中文：\n"
    else:
        raise ValueError(f"Unknown mode: {mode}")
    appeared_names = get_appeared_names(text, name_convention)

    ## Soft
    if len(appeared_names) > 0:
        if type(list(appeared_names.values())[0]) is dict:
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
                        # Add three longest aliases
                        aliases = sorted(
                            appeared_names[key]["alias"], key=lambda x: len(x), reverse=True
                        )[:3]
                        aliases = [alias for alias in aliases if alias != key]
                        if len(aliases) > 0:
                            ppt += "，别名有" + '、'.join(aliases)
                        ppt += f"，应翻译为【{appeared_names[key]['cn_name']}】。\n"
                    elif "地名" in appeared_names[key]['info']:
                        ppt += f"【{key}】是地名，应翻译为【{appeared_names[key]['cn_name']}】。\n"
                    elif "組織名" in appeared_names[key]['info']:
                        ppt += f"【{key}】是组织名，应翻译为【{appeared_names[key]['cn_name']}】。\n"
                    else:
                        ppt += f"【{key}】，应翻译为【{appeared_names[key]['cn_name']}】。\n"
            prompt = ppt + '\n' + prompt

        elif mode == "sakura":
            ppt = "在翻译时，遵守如下的日中人名/地名惯例：\n"
            ppt += "\n".join([f"{key} -> {value}" for key, value in list(appeared_names.items())[:20] if key in text])
            prompt = ppt + '\n' + prompt
        else:
            prompt += "在翻译时，尽量不要包含任何英文，遵守如下的日中人名/地名惯例：\n"
            prompt += "\n".join([f"{key} = {value}" for key, value in list(appeared_names.items())[:20] if key in text])

    if mode == "sakura":
        return prompt + text

    ## Hard
    # for jp_name in appeared_names:
    #     if len(jp_name) >= 3 and jp_name not in soft_name_convention:
    #         pattern = r'(?<!\uff08)' + re.escape(jp_name) + r'(?!\uff09)'
    #         if len(appeared_names) > 0 and type(list(appeared_names.values())[0]) is dict:
    #             cn_name = appeared_names[jp_name]['cn_name']
    #         else:
    #             cn_name = appeared_names[jp_name]
    #         text = re.sub(pattern, cn_name, text)

    prompt += "\n\n---------------以下是日文原文---------------\n\n"
    if "无法翻译" in text or "无法翻译" in prompt:
        raise

    text = prompt + text
    if "无法翻译" in text or "无法翻译" in prompt:
        raise
    text += "\n\n---------------以下是中文翻译---------------\n\n"

    return text


if __name__ == "__main__":
    text = """【書籍化】ビギニングノベルズ様より第2巻発売中。
闇の魔法使いによって国を滅ぼされた王女マキナ。祖国復興のため、魔法使いの冒険者として幼馴染の騎士テットと共に旅に出る。
しかしその行く先々で待ち受けていたのは、仇敵に刻まれた『烙印』による、抗えない発情と肉欲の日々だった。
※普段は清純なお姫様が色々な男とヤリまくるよってお話。
    """
    logger.info(generate_prompt(text, mode="sakura"))
