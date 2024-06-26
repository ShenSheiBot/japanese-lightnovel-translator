from utils import load_config, SqlWrapper, toggle_kana, has_kana
import os
import json


config = load_config()


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
    # Remove standalone names: count < 3
    names = {name: names[name] for name in names if names[name]['count'] >= 3}

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


if __name__ == "__main__":
    names = {}
    
    with open(os.path.join('output', config['CN_TITLE'], 'ruby.json'), encoding='utf-8') as f:
        ruby = json.loads(f.read())

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
