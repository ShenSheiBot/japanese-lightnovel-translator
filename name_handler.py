import re
from loguru import logger
from utils import replace_repeater_char, has_kana, postprocessing, find_first_east_asian


def handle_name(jp_name, cn_name, prompt, jp_text, name_convention):
    cn_name = replace_repeater_char(cn_name)
    
    if jp_name not in jp_text:
        # prompt += f"你回答的 {jp_name}={cn_name} 是错的，原文中没有{jp_name}。\n\n"
        logger.error(f"Name rejected due to not in text: {jp_name}={cn_name}")
        return prompt
    
    if jp_name.endswith("さん"):
        jp_name = jp_name[:-2]
        if cn_name.endswith("先生") or cn_name.endswith("小姐"):
            cn_name = cn_name[:-2]
    
    if jp_name.endswith("先生"):
        jp_name = jp_name[:-2]
        if cn_name.endswith("老师"):
            cn_name = cn_name[:-2]
            
    if jp_name.endswith("くん"):
        jp_name = jp_name[:-2]
        if cn_name.endswith("君"):
            cn_name = cn_name[:-1]
    
    if not has_kana(cn_name) and not has_kana(jp_name):
        # Chinese to Hanzi name translation, but unequal lenghts
        if len(jp_name) != len(cn_name):
            return prompt
        # None of the characters are equal
        if all([jc != cc for jc, cc in zip(jp_name, cn_name)]):
            return prompt
        
    ## Remove postfix
    if len(jp_name) > 3:
        for i in list(range(2, len(jp_name)))[::-1]:
            if jp_name[:i] in name_convention:
                jp_name = jp_name[:i]
                cn_name = name_convention[jp_name[:i]][0]
                break
    weight = 10 if has_kana(jp_name) else 1
    
    if "（" in jp_name or "『" in jp_name or "「" in jp_name:
        # prompt += f"你回答的 {jp_name}={cn_name} 是错的，只回答名字，不要包含括号/引号。\n\n"
        logger.error(f"Name rejected due to brackets: {jp_name}={cn_name}")
        return prompt
    if has_kana(cn_name) and jp_name not in name_convention:
        # prompt += f"你回答的 {jp_name}={cn_name} 是错的，右侧的{cn_name}包含了日文才有的假名。\n\n"
        logger.error(f"Name rejected due to kana: {jp_name}={cn_name}")
        return prompt
    
    ## Handle <>, 《》,「」 situation
    # Define regex for matching text inside the brackets
    bracket_patterns = [r'\<(.*?)\>', r'《(.*?)》', r'「(.*?)」']

    # Process each bracket type separately
    for pattern in bracket_patterns:
        # Find all matches for the current bracket type in both names
        jp_bracket_contents = re.findall(pattern, jp_name)
        cn_bracket_contents = re.findall(pattern, cn_name)
        
        # Proceed only if the number of bracketed segments match
        if len(jp_bracket_contents) == len(cn_bracket_contents):
            # Replace the bracketed segments with a placeholder to handle later
            jp_name = re.sub(pattern, '{}', jp_name)
            cn_name = re.sub(pattern, '{}', cn_name)

            # Process each bracketed segment pair
            for jp_segment, cn_segment in zip(jp_bracket_contents, cn_bracket_contents):
                prompt = handle_name(jp_segment, cn_segment, prompt, jp_text, name_convention)
        else:
            logger.error(f"Bracketed segments do not match: {jp_name}={cn_name}")
            return prompt

    # Now process the unbracketed parts of the names, if placeholders were used
    if '{}' in jp_name:
        # Split the names on the placeholder
        jp_segments = jp_name.split('{}')
        cn_segments = cn_name.split('{}')

        # Process each unbracketed segment pair
        for jp_segment, cn_segment in zip(jp_segments, cn_segments):
            if jp_segment and cn_segment:  # Ensure neither segment is empty
                prompt = handle_name(jp_segment, cn_segment, prompt, jp_text, name_convention)
        return prompt
    
    ## Handle A·B situation
    if "·" in jp_name or "・" in jp_name or "·" in cn_name or "・" in cn_name:
        jp_name = jp_name.replace("・", "·")
        cn_name = cn_name.replace("・", "·")
        jp_names = jp_name.split("·")
        cn_names = cn_name.split("·")
        if len(jp_names) != len(cn_names):
            logger.error(f"Name rejected due to unequal number of segments: {jp_name}={cn_name}")
            return prompt
        for jp_name, cn_name in zip(jp_names, cn_names):
            prompt = handle_name(jp_name, cn_name, prompt, jp_text, name_convention)
                
    if len(jp_name) < 2:
        logger.error(f"Name too short: {jp_name}={cn_name}")
        return prompt
            
    if len(jp_name) > 10 or len(cn_name) > 10:
        logger.error(f"Name too long: {jp_name}={cn_name}")
        return prompt
    
    if postprocessing(jp_name) == cn_name:
        logger.error(f"Name already equal: {jp_name}={cn_name}")
        return prompt
            
    if jp_name not in name_convention:
        name_convention[jp_name] = (cn_name, weight)
        logger.critical(f"New name: {jp_name}={cn_name}")
    else:
        cn_name, count = name_convention[jp_name]
        name_convention[jp_name] = (cn_name, count + weight)
    return prompt


def check_names(name_convention, names, jp_text):
    names = [find_first_east_asian(line).split('=') for line in names.split('\n')
                if '=' in line and len(find_first_east_asian(line).split('=')) == 2
                and "（" not in line and "(" not in line]
    name_dict = {line[0]: line[1] for line in names}
    prompt = ""
    for jp_name, cn_name in name_dict.items():
        jp_name = jp_name.strip()
        cn_name = cn_name.strip()
        if "翻译" in jp_name or "翻译" in cn_name:
            continue
        prompt = handle_name(jp_name, cn_name, prompt, jp_text, name_convention)
    
    if prompt != "":
        prompt += "重新回答。\n\n--------------这段文字中出现的人名/地名如下（日文名=对应中文名）："
    return prompt


if __name__ == "__main__":
    jp_name = "アツシ"
    cn_name = "阿辛"
    name_convention = {}
    print(handle_name(jp_name, cn_name, "", jp_name + cn_name, name_convention))
    print(name_convention)
