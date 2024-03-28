from ebooklib import epub
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
from copy import deepcopy
import argparse
import re
from tqdm import tqdm
from apichat import OpenAIChatApp, GoogleChatApp, PoeAPIChatApp, BaichuanChatApp, APITranslationFailure
from utils import txt_to_html, split_string_by_length, sep, postprocessing, remove_duplicate, gemini_fix
from utils import validate, remove_header, load_config, remove_leading_numbers, get_leading_numbers
from utils import has_chinese, fix_repeated_chars, update_content, has_kana, replace_section_titles
from utils import SqlWrapper, zip_folder_7z, convert_san, concat_kanji_rubi, validate_name_convention
from loguru import logger
from prompt import generate_prompt, change_list, name_convention
import re
import warnings
import yaml
import time
import uuid


warnings.filterwarnings('ignore', category=XMLParsedAsHTMLWarning)
warnings.filterwarnings('ignore', category=UserWarning)
with open("translation.yaml", "r") as f:
    translation_config = yaml.load(f, Loader=yaml.FullLoader)
webapp = None
config = load_config()
name_convention[config['JP_TITLE']] = {
    'jp_name': config['JP_TITLE'],
    'cn_name': config['CN_TITLE'],
    'alias': [config['JP_TITLE']],
    'info': ["标题"]
}


def translate(jp_text, mode="translation", dryrun=False, skip_name_valid=False):       
    flag = True
    
    jp_text = fix_repeated_chars(jp_text)
    
    if dryrun:
        return "待翻译……"
    
    ruuid = uuid.uuid4()

    logger.info(f"\n------ {ruuid} JP ------\n\n" + jp_text + "\n------------------------\n\n")
    
    for name, model in translation_config.items():
        
        if "Sakura" in name:
            prompt = generate_prompt(jp_text, mode="sakura")
            logger.info(f"\n-------- {ruuid} Prompt --------\n\n" + prompt + "\n------------------------\n\n")
        else:
            prompt = generate_prompt(jp_text, mode=mode)
            logger.info(f"\n-------- {ruuid} Prompt --------\n\n" + prompt + "\n------------------------\n\n")
        
        retry_count = model['retry_count']
        
        logger.info("Translating using " + name + " ...")
        
        ### API translation
        if model['type'] == 'api':
            if 'Gemini' in name:
                api_app = GoogleChatApp(api_key=model['key'], model_name=model['name'])
            elif 'OpenAI' in name:
                api_app = OpenAIChatApp(api_key=model['key'], model_name=model['name'], endpoint=model['endpoint'])
            elif 'Poe' in name:
                api_app = PoeAPIChatApp(api_key=model['key'], model_name=model['name'])
            elif 'Baichuan' in name:
                api_app = BaichuanChatApp(api_key=model['key'], model_name=model['name'])
            else:
                raise ValueError("Invalid model name.")
            
            name_violation_count = 0
            min_violate_count = 10000
            cn_text_bck = None
            while flag and retry_count > 0:
                try:
                    cn_text = api_app.chat(prompt)
                    cn_text = remove_header(cn_text)
                    
                    valid = validate(jp_text, cn_text, name_convention)
                    violate_count = validate_name_convention(jp_text, cn_text, name_convention)
                    valid_name = violate_count == 0
                    if skip_name_valid:
                        valid_name = True
                    if not valid or not valid_name:
                        if valid and not valid_name:
                            name_violation_count += 1
                            logger.critical(f"-------- {ruuid} Violation count {name_violation_count}")
                            if violate_count < min_violate_count:
                                min_violate_count = violate_count
                                cn_text_bck = deepcopy(cn_text)
                        if name_violation_count >= 3:
                            cn_text = cn_text_bck
                            logger.critical(f"-------- {ruuid} Fallback to min violate translation.")
                            flag = False
                            break
                        logger.critical(f"-------- {ruuid} API invalid response: ---------\n" + cn_text)
                    else:
                        flag = False
                except APITranslationFailure as e:
                    if "Connection error" in str(e) and retry_count == 1:
                        raise
                    logger.critical(f"-------- {ruuid} API translation failed: {e} ----------")
                    pass
                retry_count -= 1
                
        if not flag:
            break
                
        ### Web translation
        elif model['type'] == 'web':
            raise ValueError("Web translation is not supported.")
                
        if not flag:
            break
        
    # Fix san
    cn_text = convert_san(cn_text, name_convention=name_convention)
    logger.info(f"\n-------- {ruuid} CN ------\n\n" + cn_text + "\n------------------------\n\n")
                        
    return cn_text


def post_translate(cn_text):
    lines = []
    for line in cn_text.split('\n'):
        line_ = re.sub(r'【.*?】', '', line)
        line_ = re.sub(r'（.*?）', '', line_)
        line_ = re.sub(r'\(.*?\)', '', line_)
        if "■" in line_ or "カクヨム" in line:
            continue
        if has_kana(line_) and has_chinese(line_):
            logger.error("Line contains both Japanese and Chinese: " + line)
            prompt = f"请补完以下翻译，将包含日语的部分翻译为中文。仅回答翻译完的这句话，回答不许包含假名。\n---\n{line}"
            
            response = ""
            count = 0
            COUNT = 1
            while count < COUNT and ("翻译" in response or "抱歉" in response or has_kana(response) 
                                     or not has_chinese(response) or len(response) / len(line) < 0.5 
                                     or len(response) / len(line) > 1.5):
                if 'Poe-claude-api' not in translation_config:
                    logger.critical("Poe API is not available. Returning the original text.")
                    return cn_text
                try:
                    poe_chat = PoeAPIChatApp(api_key=translation_config['Poe-claude-api']['key'],
                                             model_name=translation_config['Poe-claude-api']['name'])
                    response = poe_chat.chat(prompt)
                except APITranslationFailure as e:
                    logger.critical(f"API translation failed: {e}")
                    count += 1
                    continue
                if not (line.startswith("「") and line.endswith("」")) \
                and (response.startswith("「") and response.endswith("」")):
                    response = response[1:-1]
                if not (line.startswith("「「") and line.endswith("」」")) \
                and (response.startswith("「「") and response.endswith("」」")):
                    response = response[1:-1]
                
                count += 1
            if count == COUNT:
                logger.error("Failed. No update to line: " + line)
            else:
                line = postprocessing(response)
                logger.error("Updated line: " + line)
        lines.append(line)
    return "\n".join(lines)


def main():
    logger.add(f"output/{config['CN_TITLE']}/info.log", colorize=True, level="DEBUG")
    parser = argparse.ArgumentParser()
    parser.add_argument("--dryrun", action="store_true")
    args = parser.parse_args()

    # Open the EPUB file
    book = epub.read_epub(f"output/{config['CN_TITLE']}/input.epub", {"ignore_ncx": False})
    modified_book = deepcopy(book)
    modified_book.items = []
    cn_book = deepcopy(book)
    cn_book.items = []

    with SqlWrapper(f"output/{config['CN_TITLE']}/buffer.db") as buffer, \
         SqlWrapper(f"output/{config['CN_TITLE']}/title_buffer.db") as title_buffer:

        # Iterate through each item in the book (chapters, sections, etc.)
        title_buffer[config['JP_TITLE']] = config['CN_TITLE']

        ############ Translate the chapter titles ############
        ncx = book.get_item_with_id("ncx")
        content = ncx.content.decode("utf-8")
        soup = BeautifulSoup(content, "html5lib")
        navpoints = soup.find_all("navpoint")
        output = ""
        jp_titles = []
        for i, navpoint in enumerate(navpoints):
            name = navpoint.find('text').get_text(strip=True)
            output += str(i) + " " + name + "\n"
            jp_titles.append(name)
        jp_titles_parts = split_string_by_length(output, 800)

        # Traverse the aggregated chapter titles
        for jp_text in jp_titles_parts:
            jp_titles_ = jp_text.strip().split('\n')
            new_jp_titles = []
            # Concatenate title to the previous one if it's a continuation
            for jp_title in jp_titles_:
                if jp_title[0].isdigit():
                    new_jp_titles.append(jp_title)
                else:
                    new_jp_titles[-1] += jp_title
            jp_titles_ = new_jp_titles

            start_idx = get_leading_numbers(jp_titles_[0])
            end_idx = get_leading_numbers(jp_titles_[-1])

            if not all([remove_leading_numbers(title) in title_buffer for title in jp_titles_]):
                cn_titles_ = []
                title_retry_count = config['TRANSLATION_TITLE_RETRY_COUNT'] + 1

                while len(cn_titles_) != len(jp_titles_) and title_retry_count > 0:
                    ### Start translation
                    if (not has_kana(jp_text) and not has_chinese(jp_text)) or args.dryrun:
                        cn_text = jp_text
                    elif jp_text in title_buffer:
                        cn_text = title_buffer[jp_text]
                    else:
                        cn_text = translate(jp_text, mode="title_translation", dryrun=args.dryrun, skip_name_valid=True)
                        title_buffer[jp_text] = cn_text
                    ### Translation finished

                    ### Match translated title to the corresponding indices
                    cn_titles_ = cn_text.strip().split('\n')
                    cn_titles_ = [title for title in cn_titles_ if get_leading_numbers(title) is not None]
                    if len(cn_titles_) == 0:
                        continue
                    if get_leading_numbers(cn_titles_[0]) == start_idx and \
                        get_leading_numbers(cn_titles_[-1]) == end_idx and \
                            len(cn_titles_) == len(jp_titles_):
                        break
                    else:
                        title_retry_count -= 1

                if len(cn_titles_) != len(jp_titles_):
                    logger.error("Title translation failed.")
                    cn_titles_ = jp_titles_

                if not args.dryrun:
                    for cn_title, jp_title in zip(cn_titles_, jp_titles_):
                        if not has_kana(jp_title) and not has_chinese(jp_title):
                            cn_title = jp_title
                        title_buffer[remove_leading_numbers(jp_title)] = remove_leading_numbers(cn_title)

        replace_section_titles(cn_book.toc, title_buffer)
        replace_section_titles(modified_book.toc, title_buffer, cnjp=True)

        total_items = 0
        for item in tqdm(list(book.get_items())):
            if isinstance(item, epub.EpubHtml) and not isinstance(item, epub.EpubNav) \
            and "TOC" not in item.id and "toc" not in item.id:
                total_items += 1
        current_items = 0
        current_time = None

        ############ Translate the chapters and TOCs ############
        for item in list(book.get_items()):

            if isinstance(item, epub.EpubHtml) and not isinstance(item, epub.EpubNav) \
            and "TOC" not in item.id and "toc" not in item.id:
                current_items += 1
                logger.info(f"Translating {item.id} ({current_items}/{total_items}) ...")
                # Estimate remaining time
                if current_items > 1:
                    elapsed_time = time.time() - current_time
                    remaining_time = elapsed_time * (total_items - current_items)
                    logger.info(f"Estimated remaining time: {remaining_time / 60:.2f} minutes")
                current_time = time.time()

                content = item.content.decode("utf-8")
                # Parse HTML and extract text
                soup = BeautifulSoup(item.content.decode("utf-8"), "html5lib")
                cn_soup = BeautifulSoup(item.content.decode("utf-8"), "html5lib")

                # for rt_tag in soup.find_all("rt"):
                #     rt_tag.decompose()
                # for rt_tag in cn_soup.find_all("rt"):
                #     rt_tag.decompose()

                if item.id == "message.xhtml":
                    # Find the div that comes after the <span>简介：</span>
                    for soup_ in [soup, cn_soup]:
                        intro_div = soup_.find('span', string='简介：')
                        if intro_div:
                            intro_div = intro_div.find_next_sibling('div')
                        else:
                            continue

                        # Check if the content inside the div doesn't already contain a <p> tag
                        if not intro_div.find('p'):
                            # Split the content by <br/> tags
                            parts = intro_div.decode_contents().split('<br/>')
                            # Rebuild the content with <p> tags between parts
                            new_content = ''.join(f'<p>{part}</p><br/>' if part.strip() else '<br/>' for part in parts)
                            # Update the div's content
                            intro_div.clear()
                            intro_div.append(BeautifulSoup(new_content, 'html.parser'))  

                if soup.body.find(["p", "h1", "h2", "h3"]):
                    # Extract paragraphs and join them with new lines
                    paragraphs = soup.find_all(["p", "h1", "h2", "h3", "img", "image"])
                    paragraphs_ = cn_soup.find_all(["p", "h1", "h2", "h3", "img", "image"])

                    # Get consecutive paragraphs and titles
                    jp_text_collection = []
                    last_p = False

                    img_sets = []

                    for p_tag, p_tag_ in zip(paragraphs, paragraphs_):
                        if p_tag.name in ["img", "image"]:
                            img_sets.append((p_tag, p_tag_))
                        if p_tag.name != "p":
                            jp_text_collection.append((p_tag.get_text(), p_tag.name, [p_tag], [p_tag_]))
                            last_p = False
                        elif last_p:
                            text, tag, ps, ps_ = jp_text_collection[-1]
                            ps.append(p_tag)
                            ps_.append(p_tag_)
                            jp_text_collection[-1] = (text + '\n' + p_tag.get_text(), tag, ps, ps_)
                        else:
                            jp_text_collection.append((p_tag.get_text(), p_tag.name, [p_tag], [p_tag_]))
                            last_p = True

                    for jp_texts, name, ps, ps_ in jp_text_collection:
                        locator = ps[0]
                        locator_ = ps_[0]

                        # Handle paragraph
                        if name == "p":
                            # Modify chapter_text using change function
                            jp_text_parts = split_string_by_length(jp_texts)

                            decomposable = len(jp_text_parts) > 0
                            for jp_text in jp_text_parts:

                                # Remove images
                                img_pattern = re.compile(r'<img[^>]+>')
                                imgs = img_pattern.findall(jp_text)
                                jp_text = img_pattern.sub('', jp_text)
                                jp_text = concat_kanji_rubi(jp_text)

                                # Remove first line if contain title and 作
                                first_line = jp_text.strip().split("\n")[0].strip()
                                if "作" in first_line and re.sub(
                                    r"\s", "", config["JP_TITLE"]
                                ) in re.sub(r"\s", "", first_line):
                                    jp_text = jp_text.replace(first_line + '\n', '')

                                if len(jp_text.strip()) == 0:
                                    cn_text = ""
                                    decomposable = False
                                elif (not has_kana(jp_text) and not has_chinese(jp_text)):
                                    cn_text = jp_text
                                elif jp_text in buffer and validate(jp_text, buffer[jp_text], name_convention) and \
                                all([item not in jp_text for item in change_list]):
                                    cn_text = buffer[jp_text]
                                else:
                                    ### Start translation
                                    cn_text = translate(jp_text, dryrun=args.dryrun, skip_name_valid=True)
                                    cn_text = gemini_fix(cn_text)
                                    cn_text = post_translate(cn_text)
                                    ### Translation finished

                                    cn_text = remove_duplicate(cn_text)
                                    if not args.dryrun:
                                        buffer[jp_text] = cn_text

                                cn_text = postprocessing(cn_text, verbose=not args.dryrun)
                                jp_text = txt_to_html(jp_text)
                                cn_text = txt_to_html(cn_text)

                                jp_element = BeautifulSoup(jp_text, "html5lib").find()
                                cn_element = BeautifulSoup(cn_text, "html5lib").find()

                                locator.insert_before(jp_element)
                                if decomposable:
                                    locator.insert_before(sep())
                                locator.insert_before(cn_element)
                                if decomposable:
                                    locator.insert_before(sep())

                                cn_element_ = BeautifulSoup(cn_text, "html5lib").find()
                                locator_.insert_before(cn_element_)

                                for img in imgs:
                                    img = BeautifulSoup(img, "html5lib")
                                    cn_element.insert_before(img)
                                    cn_element_.insert_before(img)

                            # Removing all <p> elements within the <body> tag
                            if decomposable:
                                for p_tag in ps_ + ps:  # Combining the lists for simplicity
                                    imgs = p_tag.find_all("img")
                                    if not imgs:  # If there are no <img> tags, decompose the <p> tag
                                        p_tag.decompose()

                        # Handle images
                        elif name in ["img", "image"]:
                            # Do nothing
                            pass

                        # Handle titles
                        else:
                            decomposable = True

                            jp_title = jp_texts
                            if len(jp_title.strip()) == 0:
                                cn_title = ""
                                decomposable = False
                            elif jp_title in title_buffer:
                                cn_title = title_buffer[jp_title]
                            elif not has_kana(jp_title) or "作者" in jp_title:
                                cn_title = jp_title
                            else:
                                ### Start translation
                                cn_title = translate(jp_title, dryrun=args.dryrun, skip_name_valid=True)
                                ### Translation finished
                                title_buffer[jp_title] = cn_title

                            jp_title = txt_to_html(jp_title, tag=name)
                            cn_title = txt_to_html(cn_title, tag=name)

                            jp_element = BeautifulSoup(jp_title, "html5lib").find()
                            cn_element = BeautifulSoup(cn_title, "html5lib").find()
                            locator.insert_before(jp_element)
                            locator.insert_before(BeautifulSoup("<br/>", "html5lib").find())
                            locator.insert_before(cn_element)

                            cn_element_ = BeautifulSoup(cn_title, "html5lib").find()
                            locator_.insert_before(cn_element_)

                            if decomposable:
                                for p_tag in ps_ + ps:  # Combining the lists for simplicity
                                    imgs = p_tag.find_all("img")
                                    if not imgs:  # If there are no <img> tags, decompose the <p> tag
                                        p_tag.decompose()
                else:
                    # Full image page, convert all images to full page
                    for img in soup.find_all(["image", "img"]):
                        if "width" in img.attrs and "height" in img.attrs:
                            width = img.attrs["width"]
                            height = img.attrs["height"]
                            img.attrs["width"] = "600"
                            img.attrs["height"] = str(int(600 * int(height) / int(width)))
                    for img in cn_soup.find_all(["image", "img"]):
                        if "width" in img.attrs and "height" in img.attrs:
                            width = img.attrs["width"]
                            height = img.attrs["height"]
                            img.attrs["width"] = "600"
                            img.attrs["height"] = str(int(600 * int(height) / int(width)))

                update_content(item, modified_book, title_buffer, soup)
                update_content(item, cn_book, title_buffer, cn_soup)

            ### Handle TOC and Ncx updates
            elif isinstance(item, epub.EpubNcx) or \
            (isinstance(item, epub.EpubHtml) and ("TOC" in item.id or "toc" in item.id)):

                # Update titles to CN titles or CN+JP titles in TOC
                content = item.content.decode("utf-8")
                cn_content = deepcopy(content)
                jp_titles.sort(key=lambda x: len(x), reverse=True)
                for jp_title in jp_titles:
                    if jp_title in title_buffer:
                        cn_title = title_buffer[jp_title]
                        content = content.replace(jp_title, cn_title)
                        cn_content = cn_content.replace(jp_title, cn_title)

                update_content(item, modified_book, title_buffer, content)
                update_content(item, cn_book, title_buffer, cn_content)

            else:
                # Copy other items
                modified_book.items.append(item)
                cn_book.items.append(item)

    # Save EPUB output
    namespace = 'http://purl.org/dc/elements/1.1/'

    cn_book.metadata[namespace]['language'] = []
    cn_book.set_language("zh")
    cn_book.metadata[namespace]['title'] = []
    cn_book.set_title(config['CN_TITLE'])
    modified_book.metadata[namespace]['language'] = []
    modified_book.set_language("zh")
    modified_book.metadata[namespace]['title'] = []
    modified_book.set_title(config['CN_TITLE'])

    epub.write_epub(f"output/{config['CN_TITLE']}/{config['CN_TITLE']}_cnjp.epub", modified_book)
    epub.write_epub(f"output/{config['CN_TITLE']}/{config['CN_TITLE']}_cn.epub", cn_book)
    zip_folder_7z(
        f"output/{config['CN_TITLE']}/", 
        f"output/{config['CN_TITLE']}/{config['CN_TITLE']}【密码为前10字】.7z",
        password=config['CN_TITLE'][:10]
    )


if __name__ == "__main__":
    main()
