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
                        # Add three longest aliases
                        # aliases = sorted(
                        #     appeared_names[key]["alias"], key=lambda x: len(x), reverse=True
                        # )[:3]
                        # aliases = [alias for alias in aliases if alias != key]
                        # if len(aliases) > 0:
                        #     ppt += "，别名有" + '、'.join(aliases)
                        ppt += f"，应翻译为【{appeared_names[key]['cn_name']}】。\n"
                    elif "地名" in appeared_names[key]['info']:
                        ppt += f"【{key}】是地名，应翻译为【{appeared_names[key]['cn_name']}】。\n"
                    elif "組織名" in appeared_names[key]['info']:
                        ppt += f"【{key}】是组织名，应翻译为【{appeared_names[key]['cn_name']}】。\n"
                    else:
                        ppt += f"【{key}】，应翻译为【{appeared_names[key]['cn_name']}】。\n"
            prompt = ppt + '\n' + prompt

        elif mode == "sakura":
            ppt = "术语表：\n"
            ppt += "\n".join(
                [
                    f"{key} = {value['cn_name']}"
                    for key, value in list(appeared_names.items())[:20]
                    if key in text
                ]
            )
            prompt = ppt + '\n' + prompt
        else:
            prompt += "在翻译时，尽量不要包含任何英文，遵守如下的日中人名/地名惯例：\n"
            prompt += "\n".join([f"{key} = {value}" for key, value in list(appeared_names.items())[:20] if key in text])

    if mode == "sakura":
        for key, value in list(appeared_names.items())[:20]:
            text = text.replace(key, value['cn_name'])
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


if __name__ == "__main__":
    text = """嫉妬している自分の心が、酷く醜いように思えた。
理由は明確で、ポリドロ卿があのサムライとやらに酷く優し気であり――まあ、その割に鉄靴で頭を蹴り飛ばす素振りなども見せていたが、騎士の優しさは決闘相手を傷付けぬ事ではない。
それが真剣勝負であるならば、仮に自分の主君とて討ち果たさなければならぬ。
武人としては双方、この以上ない敬意を払った結果があの勝負であった。
ハッキリ言えば二人だけの世界に入っており、私やユエ殿など邪魔者とすら見ていた。
気に食わない。
私とて、あのようにポリドロ卿に想われたかった。
ポリドロ卿は私の心内など知らぬだろうが、私は貴方と小さな家族を作りたいのだと。
そのような軟弱な心など打ち明けられぬのが、もどかしかった。
とはいえ、立会人の務めは果たさねばならぬ。
私とユエ殿、そしてポリドロ卿の三人は無事を確認したサムライを置き去りにし、再び三人そろって歩き出した。
当然、また超人と出くわす。
超人は今までの異邦人と違い、同国たる神聖グステン帝国内の者であると思われる。
というよりも――
「ケルン？」
思わず呟いた。
兜は脱いでいる。
煌めくような銀髪の麗人であった。
胸甲冑にはクロス・アンド・サークルの紋章が刻まれている。
ありとあらゆるケルン派教徒が使用を許されている紋章である。
知っての通り、ケルン派は頭がおかしい。
あのような紋章を好んで使う騎士などそうおらぬ。
そもそも、騎士であるならば盾に、家の紋章、あるいはそれを少しばかり変化させた紋章を刻むのだ。
仮に、ケルン派の紋章を意図的に誇示するものがいるとすれば、それは――
「ケルン派司教領の騎士であられるか？」
私より先に、ポリドロ卿が問うた。
知っての通り、ポリドロ卿もケルン派の信徒である。
答えはすぐに出たのだろう。
「仰る通りであります。ポリドロ卿」
ケルン騎士は答えた。
「『狂える猪の騎士団』に私以外の信徒はおりませぬ。それゆえに私は『ケルン』と呼ばれております。我が騎士団の全ては、愛称やテメレール様より頂戴した名など、その者が名乗るものでしかお互いを知りませぬがゆえに」
随分と変わった騎士団である。
そして、随分と変人ばかりを集めている。
とはいえ、ケルン派教会からどうやって騎士を動員しているのだ？
何の関りがある、と悩んだが。
先に、ポリドロ卿が憶測を口にした。""" # noqa

    # print(len(name_convention))
    # logger.info(generate_prompt(text))
    # import yaml
    # with open("translation.yaml", "r") as f:
    #     translation_config = yaml.load(f, Loader=yaml.FullLoader)
    # from apichat import PoeAPIChatApp, GoogleChatApp
    # # chat = PoeAPIChatApp(
    # #     api_key=translation_config['Poe-claude-api']['key'], 
    # #     model_name=translation_config['Poe-claude-api']['name']
    # # )
    # chat = GoogleChatApp(
    #     api_key=translation_config['Gemini-Pro-api']['key'], 
    #     model_name='gemini-pro'
    # )
    # logger.info(chat.chat(generate_prompt(text)))
