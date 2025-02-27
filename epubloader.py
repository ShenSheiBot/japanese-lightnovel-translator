from ebooklib import epub
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
from copy import deepcopy
import argparse
import re
from tqdm import tqdm
from apichat import OpenAIChatApp, GoogleChatApp, PoeAPIChatApp, AnthropicChatApp, APITranslationFailure
from utils import txt_to_html, split_string_by_length, sep, postprocessing, remove_duplicate, gemini_fix
from utils import validate, remove_header, load_config, remove_leading_numbers, get_leading_numbers
from utils import has_chinese, fix_repeated_chars, update_content, has_kana, replace_section_titles
from utils import get_filtered_tags, extract_toc_titles, remove_vertical_rl
from utils import SqlWrapper, zip_folder_7z, convert_san, concat_kanji_rubi, validate_name_convention
from loguru import logger
from prompt import generate_prompt, change_list, name_convention, sakura_prompt
import re
import warnings
import yaml
import time
import uuid
import random
import string


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


def translate(jp_text, mode="translation", dryrun=False, skip_name_valid=False, context=None):       
    flag = True
    
    jp_text = fix_repeated_chars(jp_text)
    
    if dryrun:
        return "待翻译……"
    
    ruuid = uuid.uuid4()

    logger.info(f"\n------ {ruuid} JP ------\n\n" + jp_text + "\n------------------------\n\n")
    
    for name, model in translation_config.items():
        
        if "Sakura" in name:
            mode = "sakura"
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
            elif 'Claude' in name:
                api_app = AnthropicChatApp(api_key=model['key'], model_name=model['name'])
            else:
                raise ValueError("Invalid model name.")
            
            if context:
                api_app.messages = context
            
            name_violation_count = 0
            min_violate_count = 10000
            cn_text_bck = None
            if "Poe" in name and api_app.messages:
                # Replace all role assistant by bot
                for i, message in enumerate(api_app.messages):
                    if message['role'] == 'assistant':
                        api_app.messages[i]['role'] = 'bot'
            else:
                # Replace all role bot by assistant
                for i, message in enumerate(api_app.messages):
                    if message['role'] == 'bot':
                        api_app.messages[i]['role'] = 'assistant'
            while flag and retry_count > 0:
                try:
                    cn_text = api_app.chat(prompt)
                    cn_text = remove_header(cn_text)
                    
                    valid = validate(jp_text, cn_text, name_convention)
                    text_new_line_count = cn_text.count("\n")
                    input_new_line_count = jp_text.count("\n")
                    if input_new_line_count > 3:
                        if text_new_line_count / input_new_line_count < 0.5:
                            retry_count += 1
                    
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
                        if 'NAME_VIOLATION_LIMIT' in config and name_violation_count >= config['NAME_VIOLATION_LIMIT']:
                            cn_text = cn_text_bck
                            logger.critical(f"-------- {ruuid} Fallback to min violate translation.")
                            flag = False
                            break
                        logger.critical(f"-------- {ruuid} API invalid response: ---------\n" + cn_text)
                    else:
                        flag = False
                # finally:
                #     pass
                except APITranslationFailure as e:
                    if "Connection error" in str(e) and retry_count == 1:
                        raise
                    if "rate limit" in str(e):
                        retry_count += 1
                    if "503 Service Unavailable" in str(e):
                        retry_count += 1
                        # Sleep for 10 minutes
                        time.sleep(600)
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
        lines.append(line)
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dryrun", action="store_true")
    parser.add_argument("--cn-title", type=str)
    parser.add_argument("--jp-title", type=str)
    
    args = parser.parse_args()
    if args.cn_title:
        config['CN_TITLE'] = args.cn_title
    if args.jp_title:
        config['JP_TITLE'] = args.jp_title
    
    logger.add(f"output/{config['CN_TITLE']}/info.log", colorize=True, level="DEBUG")

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
        jp_titles = extract_toc_titles(book)
        output = ""
        for i, name in enumerate(jp_titles):
            output += str(i) + " " + name + "\n"
        jp_titles_parts = split_string_by_length(output, config["TITLE_SPLIT_LEN"])

        # Traverse the aggregated chapter titles
        prev_jp_text = []
        prev_cn_text = []

        for jp_text in jp_titles_parts:
            jp_titles_ = jp_text.strip().split('\n')
            if len(jp_text.strip()) == 0:
                continue
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
                    elif jp_text in title_buffer and validate(jp_text, title_buffer[jp_text], name_convention):
                        cn_text = title_buffer[jp_text]
                    else:
                        context = []
                        for pj, pc in zip(prev_jp_text, prev_cn_text):
                            context += [
                                {"role": "user", "content": sakura_prompt(pj, name_convention, mode="soft")},
                                {"role": "bot", "content": pc},
                            ]
                        if context == []:
                            context = None
                        cn_text = translate(
                            jp_text,
                            mode="title_translation",
                            dryrun=args.dryrun,
                            skip_name_valid=False,
                            context=context,
                        )
                        title_buffer[jp_text] = cn_text
                    ### Translation finished

                    ### Match translated title to the corresponding indices
                    cn_text = postprocessing(cn_text)
                    cn_titles_ = cn_text.strip().split('\n')
                    cn_titles_ = [title for title in cn_titles_ if get_leading_numbers(title) is not None]
                    if len(cn_titles_) == 0:
                        continue
                    if get_leading_numbers(cn_titles_[0]) == start_idx and \
                        get_leading_numbers(cn_titles_[-1]) == end_idx and \
                            len(cn_titles_) == len(jp_titles_) and validate(jp_text, cn_text, name_convention):
                        break
                    else:
                        title_retry_count -= 1

                if len(cn_titles_) != len(jp_titles_):
                    logger.error("Title translation failed.")
                    cn_titles_ = jp_titles_

                prev_jp_text.append(jp_text)
                prev_cn_text.append(cn_text)
                if len(prev_jp_text) > config["TITLE_CONTEXT_LEN"]:
                    prev_jp_text.pop(0)
                    prev_cn_text.pop(0)

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
        prev_jp_text = []
        prev_cn_text = []

        ############ Translate the chapters and TOCs ############
        for item in tqdm(book.get_items(), total=total_items, unit="item"):
            # Check if item is CSS
            if item.media_type == "text/css":
                css_content = item.content.decode('utf-8')
                # Remove vertical-rl properties
                modified_css = remove_vertical_rl(css_content)
                item.content = modified_css.encode('utf-8')
            
            if isinstance(item, epub.EpubHtml) and not isinstance(item, epub.EpubNav) \
            and "TOC" not in item.id and "toc" not in item.id:
                logger.info(f"Translating {item.id} ({current_items}/{total_items}) ...")
                current_items += 1

                content = item.content.decode("utf-8")
                # Parse HTML and extract text
                soup = BeautifulSoup(item.content.decode("utf-8"), "html5lib")
                cn_soup = BeautifulSoup(item.content.decode("utf-8"), "html5lib")

                for rt_tag in soup.find_all("rp"):
                    rt_tag.decompose()
                for rt_tag in cn_soup.find_all("rp"):
                    rt_tag.decompose()
                for rt_tag in soup.find_all("rt"):
                    rt_tag.decompose()
                for rt_tag in cn_soup.find_all("rt"):
                    rt_tag.decompose()

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

                if soup.body.find(["p", "h1", "h2", "h3", "h4", "h5", "h6"]):
                    # Extract paragraphs and join them with new lines
                    paragraphs = get_filtered_tags(soup)
                    paragraphs_ = get_filtered_tags(cn_soup)

                    # Get consecutive paragraphs and titles
                    jp_text_collection = []
                    last_p = False

                    img_sets = []

                    for p_tag, p_tag_ in zip(paragraphs, paragraphs_):
                        if len(p_tag.get_text()) == 0:
                            continue
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
                        if locator.parent is None:
                            continue
                        locator_ = ps_[0]

                        # Handle paragraph
                        if name == "p":
                            # Modify chapter_text using change function
                            jp_text_parts = split_string_by_length(jp_texts, config["MAX_LENGTH"])

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
                                    decomposable = True
                                elif (
                                    jp_text in buffer
                                    and validate(
                                        jp_text, buffer[jp_text], name_convention
                                    )
                                    and all(
                                        [item not in jp_text for item in change_list]
                                    )
                                ):
                                    decomposable = True
                                    cn_text = buffer[jp_text]
                                else:
                                    decomposable = True
                                    ### Start translation
                                    context = []
                                    for pj, pc in zip(prev_jp_text, prev_cn_text):
                                        context += [
                                            {"role": "user", 
                                             "content": sakura_prompt(pj, name_convention, mode="soft")},
                                            {"role": "bot", "content": pc},
                                        ]
                                    if context == []:
                                        context = None
                                    cn_text = translate(
                                        jp_text,
                                        dryrun=args.dryrun,
                                        context=context,
                                        skip_name_valid=False
                                    )
                                    cn_text = gemini_fix(cn_text)
                                    cn_text = post_translate(cn_text)
                                    ### Translation finished

                                    cn_text = remove_duplicate(cn_text)
                                    if not args.dryrun:
                                        buffer[jp_text] = cn_text

                                cn_text = postprocessing(cn_text, verbose=not args.dryrun)
                                prev_jp_text.append(jp_text)
                                prev_cn_text.append(cn_text)
                                if len(prev_jp_text) > config["CONTEXT_LEN"]:
                                    prev_jp_text.pop(0)
                                    prev_cn_text.pop(0)

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
                            elif jp_title in title_buffer and validate(jp_title, title_buffer[jp_title], None):
                                cn_title = title_buffer[jp_title]
                            elif not has_kana(jp_title) or "作者" in jp_title:
                                cn_title = jp_title
                            else:
                                ### Start translation
                                cn_title = translate(jp_title, dryrun=args.dryrun, skip_name_valid=True)
                                ### Translation finished
                                title_buffer[jp_title] = cn_title

                            cn_title = postprocessing(cn_title)
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
                                    p_tag.decompose()
                else:
                    for s in [soup, cn_soup]:
                        # Now, check for SVG parent and alter if necessary
                        for svg in s.find_all("svg"):
                            parent = svg.parent
                            position_in_parent = parent.contents.index(svg)
                            svg.extract()
                            for image in svg.find_all("image"):
                                new_img = soup.new_tag("img")  # Create a new <img> tag
                                if 'width' in image.attrs:
                                    new_img['width'] = "100%"
                                if 'height' in image.attrs:
                                    new_img['height'] = "auto"
                                if 'xlink:href' in image.attrs:
                                    new_img['src'] = image['xlink:href']
                                image.replace_with(new_img)

                            # Reinsert the contents of the original SVG in their original position
                            for content in reversed(svg.contents):
                                if isinstance(content, str) and not content.strip():
                                    # Skip adding empty strings that might have been just whitespace
                                    continue
                                parent.insert(position_in_parent, content)

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
    
    # Generate a password without uppercase I and lowercase l to avoid confusion
    chars = string.digits + ''.join(c for c in string.ascii_letters if c not in 'Il') + ",.-+="
    password = ''.join(random.choices(chars, k=6))
    zip_folder_7z(
        f"output/{config['CN_TITLE']}/", 
        f"output/{config['CN_TITLE']}/{config['CN_TITLE']}【密码：{password}】.7z",
        password=password
    )


if __name__ == "__main__":
    main()
