import random
import re
import os
import ast
from bs4 import BeautifulSoup
from hanziconv import HanziConv
from loguru import logger
from copy import deepcopy
from ebooklib import epub
import yaml
import sys
import zipfile
import py7zr
from py7zr import FILTER_LZMA2, FILTER_CRYPTO_AES256_SHA256, PRESET_DEFAULT, FILTER_ARM
import functools
from ja_sentence_segmenter.common.pipeline import make_pipeline
from ja_sentence_segmenter.concatenate.simple_concatenator import concatenate_matching
from ja_sentence_segmenter.normalize.neologd_normalizer import normalize
from ja_sentence_segmenter.split.simple_splitter import split_newline, split_punctuation
import sqlite3
import json
from lxml import etree


with open("translation.yaml", "r") as f:
    translation_config = yaml.load(f, Loader=yaml.FullLoader)

with open("resource/trad_char.txt", "r", encoding="utf-8") as f:
    trad_chars = set(f.read())

with open("resource/jp_char_map.json", "r", encoding="utf-8") as f:
    jp_char_map = yaml.load(f, Loader=yaml.FullLoader)


def convert_jp_char(input_string):
    for jp_char, cn_char in jp_char_map.items():
        input_string = input_string.replace(jp_char, cn_char)
    return HanziConv.toSimplified(input_string)


def load_config(filepath='.env'):
    script_dir = os.path.dirname(os.path.abspath(__file__))
    filepath = os.path.join(script_dir, filepath)
    config = {}
    with open(filepath, 'r', encoding='utf-8') as file:
        for line in file:
            if line.startswith('#'):
                continue
            if line.strip():
                key, value = line.strip().split('=', 1)
                key = key.strip()
                value = value.strip()
                # Remove quotes if value is a string that's quoted
                if (value[0] == value[-1]) and value.startswith(("'", '"')):
                    value = value[1:-1]
                # Try to evaluate value as int or float
                try:
                    value = ast.literal_eval(value)
                except (ValueError, SyntaxError):
                    pass
                config[key] = value
    return config


def remove_leading_numbers(text):
    return re.sub(r'^\d+\.?', '', text).strip()


def get_leading_numbers(text):
    result = re.match(r'\d+', text)
    if result is None:
        return None
    return int(result.group(0))


def txt_to_html(text, tag="p"):
    paragraphs = text.strip().split('\n')
    html_paragraphs = [f"<{tag}>" + p.strip() + f"</{tag}>" for p in paragraphs if p.strip() != '']
    return "\n".join(html_paragraphs)


def split_string_by_length(text, max_length=1000):
    parts = []
    count = 0
    while len(text) > max_length:
        count += 1
        split_index = text.rfind("\n", 0, max_length)
        while split_index == 0:
            text = text[1:]
            split_index = text.rfind("\n", 0, max_length)
        if split_index == -1:
            split_index = max_length
        parts.append(text[:split_index].strip())
        text = text[split_index:]
    if len(text) > 0:
        parts.append(text.strip())

    return parts


def sep():
    return BeautifulSoup("<hr>", 'html.parser')


def load_prompt(filename="resource/promptv2.txt"):
    with open(filename, 'r', encoding="utf-8") as f:
        content = f.read()
        return content


def load_random_paragraph(filename="resource/sample.txt", num_chars=500):
    with open(filename, 'r', encoding="utf-8") as f:
        content = f.read()
        content_length = len(content)

        if content_length < num_chars:
            raise ValueError(f"File {filename} does not contain enough characters.")

        start_index = random.randint(0, content_length - num_chars)
        return content[start_index:start_index + num_chars]


def replace_quotes(text):
    text = text.replace("“", "「")
    text = text.replace("”", "」")
    text = text.replace("〔", "「")
    text = text.replace("〕", "」")
    text = text.replace("‘", "『")
    text = text.replace("’", "』")
    text = text.replace("(", "（")
    text = text.replace(")", "）")
    text = re.sub(r'"(.*?)"', r'「\1」', text)
    text = re.sub(r"'(.*?)'", r'『\1』', text)
    return text


def fix_repeated_chars(line):
    pattern = r'([！a-zA-Z0-9_\u4E00-\u9FFF\u3040-\u30FF])\1{5,}'
    line = re.sub(pattern, r'\1\1\1\1\1', line)
    line = re.sub(r'[\.]{6,}', '……', line)
    line = re.sub(r'[\.]{3,5}', '…', line)
    line = re.sub(r'[・]{6,}', '……', line)
    line = re.sub(r'[・]{3,5}', '…', line)
    line = replace_quotes(line)
    return line


def has_repeated_chars(line):
    pattern = r'([a-zA-Z0-9_\u4E00-\u9FFF\u3040-\u30FF])\1{5,}'
    return bool(re.search(pattern, line))


def check_jp(text, percentage=0.3):
    """Return True if over 30% of the chars in the text are hiragana and katakana, False otherwise."""
    total_chars = len(text)
    hiragana_katakana_chars = sum(1 for char in text if is_jp(char))
    if total_chars == 0:
        return False
    return (hiragana_katakana_chars / total_chars) > percentage


def is_jp(char):
    """Return True if the character is hiragana or katakana, False otherwise."""
    return '\u3040' <= char <= '\u309F' or '\u30A0' <= char <= '\u30FF'


def remove_punctuation(text):
    # Define a pattern to match Latin, Chinese, and Japanese punctuation
    pattern = r'[!\"#$%&\'()*+,-./:;<=>?@\[\\\]^_`{|}~\u3000-\u303F\uFF00-\uFFEF「」『』…]'
    # Use re.sub() to replace the matched punctuation with an empty string
    return re.sub(pattern, '', text)


def find_first_east_asian(input_string):
    # Use regex to find the first East Asian character
    match = re.search('[\u2E80-\u9FFF\uF900-\uFAFF\uFE30-\uFE4F]', input_string)

    # If an East Asian character is found, return the string from that character onwards
    if match:
        return input_string[match.start():]
    else:
        # If no East Asian character is found, return an empty string
        return ''


def replace_ge(text):
    pattern = re.compile(r'(ge|Ge){2,}', re.IGNORECASE)
    
    def replacement(match):
        ge_count = len(match.group()) // 2
        return '咯' * ge_count
    return pattern.sub(replacement, text)


def replace_ga(text):
    pattern = re.compile(r'(ga|Ga){2,}', re.IGNORECASE)
    
    def replacement(match):
        ge_count = len(match.group()) // 2
        return '嘎' * ge_count
    return pattern.sub(replacement, text)


def replace_goro(text):
    pattern = re.compile(r'こ(こ|ろ){3,}', re.IGNORECASE)
    
    def replacement(match):
        matched_string = match.group()
        return matched_string.replace("こ", "咕").replace("ろ", "噜")
    return pattern.sub(replacement, text)


def replace_uoraaa(text):
    pattern = re.compile(r'う[ぉお]ら[ぁあ]+')
    replacement = "欧啦啦啦"
    return pattern.sub(replacement, text)


def replace_repeater_char(text):
    def replacer(match):
        char_before = match.group(1)
        return char_before + char_before
    pattern = r'(.)々'
    return re.sub(pattern, replacer, text)


def has_kana(text):
    return bool(re.search(r'[\u3040-\u309F\u30A0-\u30FA\u30FC-\u30FF]+', text))


def has_chinese(text):
    return bool(re.search(r'[\u4E00-\u9FFF]+', text))


def remove_duplicate(text):
    if "-----以下是" in text:
        lines = text.split("\n")
        filtered_lines = []
        flag = False
        for line in lines:
            if "-----以下是" in line:
                flag = True
                continue
            if flag:
                filtered_lines.append(line)
                logger.info("Kept line after 以下是: " + line)
            else:
                logger.info("Removed line before 以下是: " + line)
        text = "\n".join(filtered_lines)
    return text


def gemini_fix(text):
    text = text.replace("Uga", "咕嘎")
    text = text.replace("しゅうっ", "咻")
    text = text.replace("あうっ", "啊呜")
    text = text.replace("ちゃんと", "好好")
    text = text.replace("そもそも", "说起来")
    text = text.replace("とりあえず", "总之")
    text = text.replace("いざという", "要紧")
    text = text.replace("そのまま", "就这样")
    text = text.replace("センス", "品味")
    text = text.replace("を重ね", "重复")
    text = text.replace("それよりも", "在那之前")
    text = text.replace("ッ", "")
    text = text.replace("vagina", "小穴")
    text = text.replace("兄様", "兄长大人")
    text = text.replace("兄样", "兄长大人")
    text = text.replace("姐様", "姐姐大人")
    text = text.replace("姐样", "姐姐大人")
    text = text.replace("様", "大人")
    text = text.replace("ちゃん", "酱")
    # If text immediate before and after chan is not English character
    text = re.sub(r'(?<![A-Za-z])chan(?![A-Za-z])', "酱", text)
    # same with san
    text = re.sub(r'(?<![A-Za-z])san(?![A-Za-z])', "桑", text)
    # same with sama
    text = re.sub(r'(?<![A-Za-z])sama(?![A-Za-z])', "大人", text)
    return text


def postprocessing(text, verbose=True):
    text = text.replace("·", "・")
    text = text.replace("\\n", "\n")
    original_text = text
    original_lines = original_text.split("\n")
    
    text = text.replace("Still waiting...", "")
    text = text.replace("Assistant did not respond.", "")
    text = text.replace("Unable to reach Poe.", "")
    text = replace_ga(text)
    text = replace_ge(text)
    text = replace_goro(text)
    text = replace_uoraaa(text)
    text = fix_repeated_chars(text)
    
    if contains_trad_chars(text):
        text = HanziConv.toSimplified(text)
        text = text.replace("唿", "呼")
        text = text.replace("熘", "溜")
        text = text.replace("勐", "猛")
        text = text.replace("煳", "糊")
        text = text.replace("嵴", "脊")
        text = text.replace("着名", "著名")
        text = text.replace("着作", "著作")
        text = text.replace("着有", "著有")
        text = text.replace("显着", "显著")
        text = text.replace("噼头盖脸", "劈头盖脸")
        text = text.replace("噼开", "劈开")
    
    lines = text.split("\n")
    filtered_lines = []
    pattern = re.compile(r'^[\u0020\u3000-\u303F\u4E00-\u9FFF]*=(?!.*[\u3002])[\u0020\u3000-\u303F\u4E00-\u9FFF]*$')

    for i, (line, original_line) in enumerate(zip(lines, original_lines)):
        if i == 0 and "翻译" in line and ("：" in line or ":" in line):
            continue
        removed_keywords = ["translation", "-" * 8 + "以下"]
        removal = False
        if pattern.search(line):
            logger.info("Removed line: " + line)
            removal = True
            break
        elif "=" in line:
            line = line.replace("=", "·")
        for keyword in removed_keywords:
            if keyword in line:
                logger.info("Removed line: " + line)
                removal = True
                break
        if fix_repeated_chars(original_line) != line:
            if verbose:
                logger.debug("Modified line: " + fix_repeated_chars(original_line) + " -> " + line)
        if not removal:
            if line.count('"') == 1:
                if line.strip().startswith('"'):
                    line = line.replace('"', "「")
                if line.strip().endswith('"'):
                    line = line.replace('"', "」")
            line = line.replace(',', '，')
            line = line.replace('!', '！')
            line = line.replace('?', '？')
            line = line.replace(';', '；')
            line = line.replace(':', '：')
            line = line.replace('...', '…')
            line = line.replace('~', '～')
            line = line.replace('〈', '《')
            line = line.replace('〉', '》')
            filtered_lines.append(line)
    text = "\n".join(filtered_lines)
    return text


def contains_arabic_characters(check_string):
    arabic_pattern = re.compile(r'[\u0600-\u06FF]')  # includes the range of Arabic characters
    return bool(arabic_pattern.search(check_string))


def contains_tibetan_characters(check_string):
    tibetan_pattern = re.compile(r'[\u0F00-\u0FFF]')  # includes the range of Tibetan characters
    return bool(tibetan_pattern.search(check_string))


def contains_russian_characters(check_string):
    check_string = check_string.replace("Д", "")
    russian_pattern = re.compile(r'[А-яёЁ]')  # includes the range of Russian characters and the letter Ё/ё
    return bool(russian_pattern.search(check_string))


def contains_trad_chars(check_string):
    for char in check_string:
        if char in trad_chars:
            return True


def num_failure(input, text, name_convention=None):
    count = 0 
    if name_convention is not None:
        for jp_name, cn_name in name_convention.items():
            if jp_name in input and (
                cn_name not in text and cn_name.replace("·", "・") not in text 
                and cn_name.replace("・", "·") not in text
                and jp_name not in text and jp_name.replace(" ", "") not in text
            ):
                count += 1
    return count


def get_appeared_names(text, name_convention=None):
    appeared_names = {}
    for jp_name in name_convention.keys():
        if jp_name in text:
            appeared_names[jp_name] = name_convention[jp_name]
            
    to_del = []
    for name in appeared_names:
        for name_ in appeared_names:
            if name in name_ and name != name_:
                to_del.append(name)
    for name in to_del:
        if name in appeared_names:
            del appeared_names[name]
    return appeared_names


def validate_name_convention(input, text, name_convention=None):
    # Name convention check
    appeared_names = get_appeared_names(input, name_convention)
    if name_convention is not None:
        for jp_name, cn_name in appeared_names.items():
            if (
                cn_name not in text and cn_name.replace("·", "・") not in text 
                and cn_name.replace("・", "·") not in text
                and jp_name not in text and jp_name.replace(" ", "") not in text
                and convert_jp_char(cn_name) not in text
            ):
                logger.critical(f"Name convention not followed: {jp_name} -> {cn_name}")
                return False
    return True


def convert_san(text, name_convention):
    cn_names = {name_convention[jp_name]["cn_name"]: jp_name for jp_name in name_convention}
    for cn_name in cn_names:
        text = text.replace(f"【{cn_name}】", cn_name)
    
    def replace_san(match):
        before_san = match.group(1)
        for i in range(5, 0, -1):
            if before_san[-i:] in name_convention:
                gender = name_convention[before_san[-i:]]["info"]
            elif before_san[-i:] in cn_names:
                gender = name_convention[cn_names[before_san[-i:]]]["info"]
            else:
                continue
            if "女性" in gender:
                return before_san + "小姐"
            elif "男性" in gender:
                return before_san + "先生"
        return match.group(0)
    
    def replace_sama(match):
        before_sama = match.group(1)
        for i in range(5, 0, -1):
            if before_sama[-i:] in name_convention or before_sama[-i:] in cn_names:
                return before_sama + "大人"
        return match.group(0)
    
    text = re.sub(r"(.{1,5})さん", replace_san, text)
    text = re.sub(r"(.{1,5})san", replace_san, text)
    text = re.sub(r"(.{1,5})桑", replace_san, text)
    text = re.sub(r"(.{1,5})样", replace_sama, text)
    text = re.sub(r"(.{1,5})先生", replace_sama, text)
    text = re.sub(r"(.{1,5})小姐", replace_sama, text)

    return text.replace("さん", "桑").replace("san", "桑")


## Check if the translation is valid
def validate(input, text, name_convention=None):
    lines = text.split("\n")

    # Number of new line ratio
    text_new_line_count = text.count("\n")
    input_new_line_count = input.count("\n")
    if input_new_line_count > 3:
        if text_new_line_count / input_new_line_count < 0.5:
            logger.critical("Too few new lines.")
            return False

    if contains_russian_characters(text):
        logger.critical("Russian characters detected.")
        return False
    # if contains_arabic_characters(text):
    #     logger.critical("Arabic characters detected.")
    #     return False
    if contains_tibetan_characters(text):
        logger.critical("Tibetan characters detected.")
        return False
    for i, line in enumerate(lines):
        if (
            "】是女性" in line
            or "】是男性" in line
            or ("身份有" and "别名有" in line)
        ):
            logger.critical("Translation background entered content")
            return False
        if i == 0 and "翻译" in line and ("：" in line or ":" in line):
            continue
        if "翻译" in line or "orry" in line or "抱歉" in line or "对不起" in line \
        or "pologize" in line or "language model" in line or "able" in line or "性描写" in line \
        or "AU" in line or "policy" in line:
            score = 0
            for keyword in ["（", "【", "你", "您", "注", "对话", "请", "继续", "对话", "成人", "敏感", "章节", "冒犯", "翻译",
                            "Sorry", "sorry", "but", "continue", "chat", "conversation", "story", "generate", "able",
                            "violate", "violating", "violation", "story", "safety", "policies", "language", "model", 
                            "中文", "日语", "小说", "露骨", "侵略", "准则", "规定", "性描写", "AI", "助手", "不适当", "淫秽",
                            "平台", "政策", "以下", "日中", "这段内容", "完成你的请求"]:
                score += int(keyword in line)
            score += int(len(line) < 10)
            if score >= 3:
                logger.critical(f"Unethical translation detected.: {line}")
                return False
    if len(text) == 0:
        logger.critical("No translation provided.")
        return False
    info_ratio = len(input) / len(text)
    if info_ratio > 2:
        logger.critical("Translation too short: " + str(len(input)) + "/" + str(len(text)))
        return False
    # Remove all special chars
    text = ''.join(re.findall(r'[\u4e00-\u9fff.,!?()。，！？《》“”「」\w\sーァ-ヶ]', text))
    text = text.replace('XX', '--')
    if detect_language(input) == "Japanese":
        result = detect_language(text) == "Chinese"
    else:
        result = True
    if not result:
        logger.critical("Translation is not in Chinese.")
    return result


## Remove header
def remove_header(text):
    first_line = text.split("\n")[0]
    if "翻译" in first_line and "：" in first_line:
        text = "\n".join(text.split("\n")[1:])
    return text


def detect_language(text):
    # Counters for Japanese and English characters
    hiragana_count = 0
    katakana_count = 0
    english_count = 0
    
    # Removing non-word characters
    cleaned_text = ''.join(e for e in text if e.isalnum())

    # Total characters (excluding special characters and punctuation)
    total_characters = len(cleaned_text)
    
    # Check for empty string
    if total_characters == 0:
        return "Indeterminate"

    # Calculate counts of each character type
    for char in cleaned_text:
        # Checking Unicode ranges for Hiragana, Katakana, and English
        if '\u3040' <= char <= '\u309F':
            hiragana_count += 1
        elif '\u30A0' <= char <= '\u30FF':
            katakana_count += 1
        elif ('\u0041' <= char <= '\u005A') or ('\u0061' <= char <= '\u007A'):
            english_count += 1

    # Calculate character type ratios
    japanese_ratio = (hiragana_count + katakana_count) / total_characters
    english_ratio = english_count / total_characters

    # Apply the given conditions
    if japanese_ratio > 0.3:
        return "Japanese"
    elif english_ratio > 0.7:
        return "English"
    else:
        return "Chinese"


def replace_section_titles(nested_list, title_buffer, cnjp=False):
    for element in nested_list:
        if isinstance(element, list) or isinstance(element, tuple):
            replace_section_titles(element, title_buffer, cnjp)
        elif hasattr(element, 'title'):
            if element.title in title_buffer:
                if cnjp:
                    element.title = title_buffer[element.title] + " | " + element.title
                else:
                    element.title = title_buffer[element.title]
    return nested_list


def update_content(item, new_book, title_buffer, updated_content):
    if type(updated_content) is str:
        soup = BeautifulSoup(updated_content, "html5lib")
    else:
        assert type(updated_content) is BeautifulSoup
        soup = updated_content
        
    for a_tag in soup.find_all('a'):
        jp_text = a_tag.get_text()
        if jp_text in title_buffer:
            a_tag.string = title_buffer[jp_text]
        
    modified_item = deepcopy(item)
    modified_item.set_content(soup.encode("utf-8"))
    new_book.items.append(modified_item)
    
    if isinstance(item, epub.EpubHtml):
        links = soup.find_all('link')
        for link in links:
            href = link.attrs['href']
            if href.endswith('css'):
                modified_item.add_link(href=href, rel='stylesheet', type='text/css')


def zip_folder_7z(folder_path, output_path, password='114514'):
    """
    Create a password-protected 7z file with encrypted file names from the contents of a folder.
    Only include .epub and .json files, except for 'names.json' if 'names_updated.json' exists in the same folder.

    :param folder_path: Path to the folder to be archived.
    :param output_path: Path where the 7z file will be created.
    :param password: Password for the 7z archive.
    """
    filters = [
        {"id": FILTER_ARM},
        {"id": FILTER_LZMA2, "preset": PRESET_DEFAULT},
        {"id": FILTER_CRYPTO_AES256_SHA256},
    ]
    with py7zr.SevenZipFile(output_path, 'w', password=password, filters=filters) as archive:
        # Add ad.jpg to the archive
        ad_path = os.path.join(os.getcwd(), 'ad.jpg')
        archive.write(ad_path, 'ad.jpg')

        for root, dirs, files in os.walk(folder_path):
            # Check for 'names_updated.json' in the current folder
            names_updated_exists = 'names_updated.json' in files

            # Filter the files to include only .epub and .json files
            files_to_add = [f for f in files if f.endswith('.epub') or f.endswith('.json')]

            for file_name in files_to_add:
                # Skip 'names.json' if 'names_updated.json' exists in the same folder
                if names_updated_exists and file_name == 'names.json':
                    continue

                file_path = os.path.join(root, file_name)
                archive_path = os.path.relpath(file_path, folder_path)  # Preserve folder structure within the archive
                archive.write(file_path, archive_path)

        # Encrypt the file names
        archive.set_encrypted_header(True)


class SqlWrapper:
    def __init__(self, db_path):
        self.db_path = db_path
        self.conn = sqlite3.connect(self.db_path)
        self.cursor = self.conn.cursor()
        self.cursor.execute('CREATE TABLE IF NOT EXISTS data (key TEXT PRIMARY KEY, value TEXT)')
        self.conn.commit()
    
    def items(self):
        self.cursor.execute('SELECT key, value FROM data')
        return self.cursor.fetchall()

    def __getitem__(self, key):
        self.cursor.execute('SELECT value FROM data WHERE key=?', (key,))
        result = self.cursor.fetchone()
        if result:
            return result[0]
        raise KeyError(key)

    def __setitem__(self, key, value):
        self.cursor.execute('INSERT OR REPLACE INTO data (key, value) VALUES (?, ?)', (key, value))
        self.conn.commit()

    def __delitem__(self, key):
        if key in self:
            self.cursor.execute('DELETE FROM data WHERE key=?', (key,))
            self.conn.commit()
        else:
            raise KeyError(key)

    def __contains__(self, key):
        self.cursor.execute('SELECT 1 FROM data WHERE key=?', (key,))
        return self.cursor.fetchone() is not None

    def close(self):
        self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def __del__(self):
        self.close()


def get_consecutive_name_entities(entities, score_threshold=0.9):
    # Initialize variables
    consecutive_entities = []
    current_entity = None
    current_entity_score = 0.0
    current_entity_text = ""
    current_entity_start = -1
    current_entity_end = None
    
    for entity in entities:
        # Check if the score meets the threshold
        if entity['score'] >= score_threshold:
            # If we're at the start of a new entity or in the middle of one
            if current_entity is None or entity['start'] == current_entity_end or \
            (entity['start'] == current_entity_end + 1 and entity['word'].startswith('▁')):
                # Start a new entity or continue building it
                current_entity = entity['entity']
                current_entity_score += entity['score']
                current_entity_text += entity['word']
                current_entity_end = entity['end']
                # Set the start position for a new entity
                if current_entity_start == -1:
                    current_entity_start = entity['start']
            else:
                # We've reached a new entity, so save the previous one
                if current_entity_text != '▁':
                    consecutive_entities.append(current_entity_text)
                # Start a new entity
                current_entity = entity['entity']
                current_entity_score = entity['score']
                current_entity_text = entity['word']
                current_entity_start = entity['start']
                current_entity_end = entity['end']
        else:
            # Score threshold not met; reset the current entity
            if current_entity is not None:
                consecutive_entities.append(current_entity_text)
            current_entity = None
            current_entity_score = 0.0
            current_entity_text = ""
            current_entity_start = -1
            current_entity_end = -1
    
    # Check if the last entity should be added to the list
    if current_entity is not None and current_entity_score >= score_threshold:
        consecutive_entities.append(current_entity_text)
    
    return consecutive_entities


def partition_names(names):
    partition = []  # List to hold strings containing "・" or "·" with all substrings present in the original list
    rest = []       # List to hold the rest of the strings

    for name in names:
        if "・" in name or "·" in name or "=" in name:
            partition.append(name)
            
            # Split the name on "・" or "·"
            subnames = name.replace("·", "・").replace("=", "・").split("・")
            # Check if subname is in the original list
            for subname in subnames:
                if subname in names and subname not in partition and subname not in rest:
                    partition.append(subname)
        elif name not in partition:
            rest.append(name)

    return partition, rest


def is_non_continuous_substring(sub, string):
    it = iter(string)
    return all(char in it for char in sub)


def partition_words(words, max_size):
    # Sort words by length in descending order to handle longer words first
    sorted_words = sorted(words, key=len, reverse=True)
    
    # Initialize the list of partitions
    partitions = []

    # Helper function to find the right partition for a word
    def find_partition(word):
        for partition in partitions:
            # Check if the word is a substring of any word in the partition
            # or vice versa, and the partition is not full
            if len(partition) < max_size and any(is_non_continuous_substring(word, w) 
                                                 or is_non_continuous_substring(w, word) for w in partition):
                return partition
        return None

    # Iterate over each word and place it in the correct partition
    for word in sorted_words:
        partition = find_partition(word)
        if partition is not None:
            partition.add(word)
        else:
            # If there's no suitable partition, create a new one
            partitions.append({word})

    # Combine partitions where possible
    combined_partitions = []
    while partitions:
        # Take a partition out of the list and try to combine it with others
        current = partitions.pop(0)
        for other in partitions[:]:
            # If they can be combined without exceeding max_size, do so
            if len(current | other) <= max_size:
                current.update(other)
                partitions.remove(other)
        combined_partitions.append(current)

    return combined_partitions


def find_first_non_consecutive_substring(s, string_set):
    def is_subsequence(sub, word):
        # This function checks if sub is a non-consecutive subsequence of word
        it = iter(word)
        return all(c in it for c in sub)

    # Iterate through each word in the set and check for non-consecutive substring
    for word in string_set:
        if is_subsequence(s, word):
            return word
    return None


def flatten(xss):
    return [x for xs in xss for x in xs]


def segment_sentences(text):
    split_punc2 = functools.partial(split_punctuation, punctuations=r"。!?")
    concat_tail_no = functools.partial(concatenate_matching, former_matching_rule=r"^(?P<result>.+)(の)$", 
                                       remove_former_matched=False)
    segmenter = make_pipeline(normalize, split_newline, concat_tail_no, split_punc2)

    return list(segmenter(text))


def find_example_sentences(names, book):
    # Combine all chapters into a single text
    full_text = ''.join(book)
    # Find all sentences in the text
    sentences = segment_sentences(full_text)

    # Dictionary to hold the example sentences for each name
    example_sentences = {name: "" for name in names}
    # Dictionary to hold the lengths of the sentences for each name
    sentence_lengths = {name: float('inf') for name in names}
    nonoptimal = {}

    # Loop through each sentence to find if it contains a name entity
    for sentence in sentences:
        for name in names:
            # Check if the name is in the sentence
            if name in sentence:
                # Highlight the name in the sentence
                if f"({name})" in sentence:
                    continue
                if ("(" in name) != (")" in name):
                    continue
                highlighted_sentence = re.sub(f"({name})", r"**\1**", sentence)
                highlighted_length = len(highlighted_sentence)
                # Check if the highlighted sentence is at least triple as long as the name
                if highlighted_length >= max(3 * len(name), 20):
                    # Check if this sentence is shorter than the current shortest acceptable sentence
                    if highlighted_length < sentence_lengths[name]:
                        example_sentences[name] = highlighted_sentence
                        sentence_lengths[name] = highlighted_length
                else:
                    nonoptimal[name] = highlighted_sentence

    # Review the collected sentences and decide which one to return for each name
    for name in names:
        # If we didn't find any suitable sentence, return a default message
        if example_sentences[name] == "":
            if name in nonoptimal:
                example_sentences[name] = nonoptimal[name]
            else:
                example_sentences[name] = f"No example sentence for **{name}**."

    return example_sentences


# 二（に）階（かい）堂（どう）亞（あ）子（こ）-> 二階堂亞子（にかいどうあこ）
def concat_kanji_rubi(text):
    kanji_kana_groups = []
    pattern = r'(([\u4E00-\u9FFF])[\（\(]([\u3040-\u309F\u30A0-\u30FA\u30FC-\u30FF]+)[\）\)])+'

    def replacement(match):
        # Here we find all submatches of the Kanji-Kana pattern within the full match.
        submatches = re.findall(
            r"([\u4E00-\u9FFF])[\（\(]([\u3040-\u309F\u30A0-\u30FA\u30FC-\u30FF]+)[\）\)]",
            match.group(0),
        )
        kanjis = ''.join(submatch[0] for submatch in submatches)
        kanas = ''.join(submatch[1] for submatch in submatches)
        kanji_kana_groups.append(f'{kanas}')
        return f'{kanjis}（{kanas}）'
    return re.sub(pattern, replacement, text)


def find_rubi(entities, full_text):
    rubies = {}    
    # Iterate over each entity (key) in the entities dictionary
    for entity in entities.keys():
        pattern = f"{entity}（"
        start_index = 0
        while True:
            start_index = full_text.find(pattern, start_index)
            if start_index == -1:
                break
            end_index = full_text.find("）", start_index)
            if end_index == -1:
                start_index += len(pattern)
                continue
            ruby = full_text[start_index + len(entity) + 1:end_index]
            if has_chinese(ruby) or has_kana(entity):
                break
            if ruby in rubies:
                if len(entity) > len(rubies[ruby]):
                    rubies[ruby] = entity
            else:
                rubies[ruby] = entity
            
            # Move the start index forward to search for the next occurrence
            start_index = end_index + 1
    
    return rubies


def extract_ruby_from_epub(epub_path):
    # Define the namespaces used in the XHTML files
    namespaces = {
        'epub': 'http://www.idpf.org/2007/ops',
        'html': 'http://www.w3.org/1999/xhtml'
    }
    
    # Unzip the ePub file into a temporary directory
    with zipfile.ZipFile(epub_path, 'r') as epub_zip:
        epub_zip.extractall('temp_epub')

    ruby_texts = {}

    # Walk through the temporary directory
    for root, _, files in os.walk('temp_epub'):
        for file in files:
            if file.endswith('.xhtml'):
                # Parse the XHTML file
                tree = etree.parse(os.path.join(root, file))
                visited_ruby = set()
                
                # Find all the <ruby> elements and extract the text
                for ruby in tree.xpath('//html:ruby', namespaces=namespaces):
                    rb_text = ''
                    rt_text = ''
                    
                    if ruby in visited_ruby:
                        continue
                    else:
                        visited_ruby = set()
                    
                    while ruby is not None:
                        rb = ruby.xpath('.//html:rb', namespaces=namespaces)
                        rt = ruby.xpath('.//html:rt', namespaces=namespaces)
                        
                        # Sometimes <rb> or <rt> might be missing, so check if they exist before trying to access text
                        rb_text += rb[0].text if rb else ''
                        rt_text += rt[0].text if rt else ''
                        
                        # Check if the next sibling is also a <ruby> element
                        ruby = ruby.getnext()
                        visited_ruby.add(ruby)
                        if ruby is None or ruby.tag != '{http://www.w3.org/1999/xhtml}ruby':
                            break
                    
                    ruby_texts[rt_text] = rb_text
    
    # Clean up the temporary directory
    os.system('rm -rf temp_epub')
    return ruby_texts


def remove_comments(string):
    lines = string.split("\n")  # Split the string into lines
    result = []
    for line in lines:
        # Check if the line contains "#" or "//"
        if "#" in line:
            line = line[:line.index("#")]  # Remove the part after "#"
        if "//" in line:
            line = line[:line.index("//")]  # Remove the part after "//"
        result.append(line)  # Add the modified line to the result list
    return "\n".join(result)  # Join the lines back into a string


def parse_gpt_json(response):
    response = remove_comments(response)
    start_idx = response.find('{')
    end_idx = response.rfind('}') + 1

    response = response[start_idx:end_idx]
    response = response.replace('\'', '\"')
    # Replace trailing comma before closing bracket
    response = re.sub(r',\s*}', '}', response)
    # Remove line containing not exactly four quotes
    response = ','.join([line for line in response.split(',') if line.count('"') == 4])
    dictionary = json.loads(response)
    return dictionary


def toggle_kana(input_string):
    # Kana Unicode blocks ranges
    HIRAGANA_START = 0x3040
    HIRAGANA_END = 0x309F
    KATAKANA_START = 0x30A0
    KATAKANA_END = 0x30FF
    KANA_GAP = KATAKANA_START - HIRAGANA_START
    
    toggled_string = ""
    
    for char in input_string:
        code_point = ord(char)
        
        # If the character is hiragana, convert to katakana
        if HIRAGANA_START <= code_point <= HIRAGANA_END:
            toggled_string += chr(code_point + KANA_GAP)
        # If the character is katakana, convert to hiragana
        elif KATAKANA_START <= code_point <= KATAKANA_END:
            toggled_string += chr(code_point - KANA_GAP)
        # If it's any other character, leave it as is
        else:
            toggled_string += char
            
    return toggled_string


def remove_common_suffix(s1, s2):
    # Reverse the strings to compare from the end
    s1_reversed = s1[::-1]
    s2_reversed = s2[::-1]

    # Find the length of the longest common suffix
    common_suffix_length = 0
    for c1, c2 in zip(s1_reversed, s2_reversed):
        if c1 == c2:
            common_suffix_length += 1
        else:
            break

    # Remove the common suffix from both strings
    if common_suffix_length > 0:
        s1 = s1[:-common_suffix_length]
        s2 = s2[:-common_suffix_length]

    return s1, s2


if __name__ == "__main__":
    print(convert_jp_char('斎藤'))
