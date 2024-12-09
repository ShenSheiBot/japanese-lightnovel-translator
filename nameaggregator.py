from utils import load_config, SqlWrapper, toggle_kana, has_kana
import os
import json
from epubparser import main
from utils import find_example_sentences
import yaml
from loguru import logger
from apichat import GoogleChatApp, PoeAPIChatApp, OpenAIChatApp, AnthropicChatApp, APITranslationFailure
from p_tqdm import p_map


config = load_config()

with open("config/nameaggregator.yaml", "r") as f:
    translation_config = yaml.load(f, Loader=yaml.FullLoader)

logger.remove()
logger.add(f"output/{config['CN_TITLE']}/agg.log", colorize=True, level="DEBUG")
buffer = SqlWrapper(os.path.join('output', config['CN_TITLE'], 'agg.db'))


def check_conflicting_tags(tag1, tag2):
    conflicting_pairs = [("人名", "地名"), ("男性", "女性")]
    return (tag1, tag2) in conflicting_pairs or (tag2, tag1) in conflicting_pairs


def find_highest_count_neighbor(entry_name, names, visited):
    highest_count = -1
    best_neighbor_name = None

    for alias in names[entry_name]['alias']:
        if alias in visited:
            continue
        visited.add(alias)
        if alias in names and 'info' in names[alias]:
            if check_conflicting_tags(names[entry_name]['info'], names[alias]['info']):
                continue 
            for tag, tag_info in names[alias]['info'].items():
                if tag in ['男性', '女性'] and tag_info['count'] > highest_count:
                    highest_count = tag_info['count']
                    best_neighbor_name = alias
    return best_neighbor_name


def merge_tags(entry_name, neighbor_name, names):
    for tag, tag_info in names[neighbor_name]['info'].items():
        if tag in names[entry_name]['info']:
            names[entry_name]['info'][tag]['count'] += tag_info['count']
        else:
            names[entry_name]['info'][tag] = tag_info


def find_aliases(names, ruby):
    # Reverse the ruby dictionary and turn key into list
    ruby_rev = {}
    for k, v in ruby.items():
        if v in ruby_rev:
            ruby_rev[v].append(k)
        else:
            ruby_rev[v] = [k]
    
    # Add the ruby to the `ruby` sections
    for name in names:
        if name in ruby_rev:
            names[name]['ruby'] = ruby_rev[name]

    # Initialize aliases dictionary
    aliases = {name: set() for name in names}
    
    # Helper function to add aliases
    def add_aliases(name, other_name):
        if not check_conflicting_tags(names[name]['info'], names[other_name]['info']):
            aliases[name].add(other_name)
            aliases[other_name].add(name)

    # Find direct aliases
    for name in names:
        for other_name in names:
            if len(name) <= 1 and has_kana(name):
                continue
            if len(other_name) <= 1 and has_kana(other_name):
                continue
            if name in other_name or other_name in name or toggle_kana(name) == other_name:
                add_aliases(name, other_name)
    
    # Sum counts and tags for each alias group
    for name in names:
        total_count = sum(names[alias]['count'] for alias in aliases[name])
        info = names[name]['info'].copy()
        
        # Update the names dictionary with the alias information
        names[name]['alias'] = list(aliases[name])
        names[name]['count'] = total_count
        names[name]['info'] = info
        
    for entry_name, entry_data in names.items():
        if '人名' in entry_data['info']:
            visited = set([entry_name])
            neighbor_name = find_highest_count_neighbor(entry_name, names, visited)
            
            def get_gender(name):
                if '男性' in names[name]['info'] and '女性' in names[name]['info']:
                    if names[name]['info']['男性']['count'] > names[name]['info']['女性']['count']:
                        return '男性'
                    return '女性'
                if '男性' in names[name]['info']:
                    return '男性'
                if '女性' in names[name]['info']:
                    return '女性'
                return None
            if neighbor_name and get_gender(entry_name) == get_gender(neighbor_name):
                merge_tags(entry_name, neighbor_name, names)
    
    # Remove aliases that are not in the names list
    for name in names:
        names[name]['alias'] = [alias for alias in names[name]['alias'] if alias in names]
    
    return names


def tagmap(tag):
    tag = tag.strip()
    if tag.startswith("人名"):
        return "人名"
    if tag.startswith("地名"):
        return "地名"
    if tag.startswith("术语") or tag.startswith("術語") or tag.endswith("術語") or tag.endswith("术语"):
        return "術語"
    if "性别" in tag or "性別" in tag:
        return "人名"
    else:
        return tag
    
    
def example_sentences_prompt(name, sentences):
    prompt = f"考虑名字【{name}】，以下是一些关于【{name}】的例句："
    for sentence in sentences:
        prompt += f"\n{sentence}"
    return prompt


def classify_no_claude(prompt: str):
    return classify(prompt, no_claude=True)


def classify(prompt: str, no_claude=False):
    # Already parsed
    if prompt in buffer:
        return buffer[prompt]
        
    for name, model in translation_config.items():
        if 'Claude' in name:
            if no_claude:
                continue
            api_app = AnthropicChatApp(api_key=model['key'], model_name=model['name'])
        elif 'Gemini' in name:
            api_app = GoogleChatApp(api_key=model['key'], model_name=model['name'])
        elif 'Poe' in name:
            api_app = PoeAPIChatApp(api_key=model['key'], model_name=model['name'])
        elif 'OpenAI' in name:
            api_app = OpenAIChatApp(api_key=model['key'], model_name=model['name'], endpoint=model['endpoint'])
        else:
            continue
        
        try:
            logger.info(prompt)
            response = api_app.chat(prompt)
            logger.info(response)
            buffer[prompt] = response[0]
            return response[0]
        except APITranslationFailure or OSError:
            continue


if __name__ == "__main__":
    names = {}
    
    try:
        with open(os.path.join('output', config['CN_TITLE'], 'ruby.json'), encoding='utf-8') as f:
            ruby = json.loads(f.read())
    except Exception:
        ruby = {}

    with SqlWrapper(os.path.join('output', config['CN_TITLE'], 'name.db')) as buffer:
        for _, entry in buffer.items():
            entry = entry.replace("'", '"')
            try:
                entry = json.loads(entry)
                assert isinstance(entry, list)
            except Exception:
                continue
            for ele in entry:
                name = ele['name']
                info = ele['info'] if 'info' in ele else ''
                
                info = set([tagmap(tag) for tag in info.replace(',', '，').split('，')])
                prev_info = set(names[name]['info'].keys()) if name in names else set()
                info = info.union(prev_info)
                entry = {
                    'name': name,
                    'info': {
                        tag: (
                            {"tag": tag, "count": names[name]['info'][tag]['count'] + 1}
                            if name in names and tag in names[name]['info']
                            else {"tag": tag, "count": 1}
                        )
                        for tag in info
                    },
                    'count': names[name]['count'] + 1 if name in names else 1,
                }
                names[name] = entry
        
        book = main(os.path.join('output', config['CN_TITLE'], 'input.epub'))
            
        # Remove standalone names: count < 3
        names = {name: names[name] for name in names if names[name]['count'] >= 3}
        example_sentences = find_example_sentences(list(names.keys()), book, count=10)
        
        # Remove names with fewer than 3 example_sentences
        names = {name: names[name] for name in names if name in example_sentences and len(example_sentences[name]) >= 3}
    
        # Remove names in exclusions.txt
        with open('resource/exclusions.txt', 'r', encoding='utf-8') as f:
            exclusions = f.read().splitlines()
        names = {name: names[name] for name in names if name not in exclusions}
        
        example_prompt = {name: example_sentences_prompt(name, example_sentences[name]) for name in names}
                
        # Remove 非专有名词
        print(len(names))
        prompts = []
        for name in example_prompt:
            prompts.append(example_prompt[name] + f"\n【{name}】是不是小说中的特定的虚构角色/虚构地名/术语（如武器、技能、物质）？"
                           "如果不是（例如东京、男性），请回答N。否则请回答Y。除了字母外，不要回答任何其他内容。")

        results = p_map(classify_no_claude, prompts, num_cpus=config['NUM_PROCS'])
        for name, result in zip(names.copy(), results):
            if result and result.startswith('N'):
                del names[name]
                
        print("After removing non-proper nouns: ", len(names))
                
        example_prompt = {name: example_prompt[name] for name in names}
        
        # Find names with conflicting genders
        unknown_gender_names = []
        for name in names:
            if '男性' in names[name]['info'] and '女性' in names[name]['info']:
                unknown_gender_names.append(name)
        
        prompts = []
        for name in unknown_gender_names:
            prompts.append(example_prompt[name] + f"\n【{name}】是男性还是女性？如果是男性，请回答M。如果是女性，请回答F。不确定，请回答U。除了字母外，不要回答任何其他内容。")
        
        results = p_map(classify, prompts, num_cpus=config['NUM_PROCS'])
        print(results)
        for name, result in zip(unknown_gender_names, results):
            print(name, '->', result)
            # Delete all gender information
            if '男性' in names[name]['info']:
                del names[name]['info']['男性']
            if '女性' in names[name]['info']:
                del names[name]['info']['女性']
            if result and result.startswith('M'):
                names[name]['info']['男性'] = {"tag": "男性", "count": 10000}
            elif result and result.startswith('F'):
                names[name]['info']['女性'] = {"tag": "女性", "count": 10000}
                
        # If name have both 人名 and 地名, go with the higher count
        for name in names:
            if '人名' in names[name]['info'] and '地名' in names[name]['info']:
                if names[name]['info']['人名']['count'] > names[name]['info']['地名']['count']:
                    names[name]['info'] = {'人名': names[name]['info']['人名']}
                else:
                    names[name]['info'] = {'地名': names[name]['info']['地名']}
                
        names = find_aliases(names, ruby)
                
        # Dump the results
        with open(f"output/{config['CN_TITLE']}/names_raw.json", "w", encoding='utf-8') as f:
            f.write(json.dumps(names, ensure_ascii=False, indent=4))
            
        print(len(names))
