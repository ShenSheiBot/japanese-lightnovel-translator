from ebooklib import epub
from bs4 import BeautifulSoup
import re
from tqdm import tqdm
from utils import split_string_by_length, load_config, concat_kanji_rubi, get_filtered_tags
import re


def main(book_name, chapterwise=False):
    if chapterwise:
        result = {}
    else:
        result = []
    config = load_config()
    
    # Open the EPUB file
    book = epub.read_epub(book_name, {"ignore_ncx": False})

    ############ Translate the chapters and TOCs ############
    for item in tqdm(list(book.get_items())):
        
        if isinstance(item, epub.EpubHtml) and not isinstance(item, epub.EpubNav) \
        and "TOC" not in item.id and "toc" not in item.id:
            
            if chapterwise:
                result[item.id] = []
            
            # Parse HTML and extract text
            soup = BeautifulSoup(item.content.decode("utf-8"), "html5lib")
            for rt_tag in soup.find_all("rp"):
                rt_tag.decompose()
            for rt_tag in soup.find_all("rt"):
                rt_tag.decompose()
            
            if soup.body.find(["p", "h1", "h2", "h3", "h4", "h5", "h6"]):
                # Extract paragraphs and join them with new lines
                paragraphs = get_filtered_tags(soup)
                
                # Get consecutive paragraphs and titles
                jp_text_collection = []
                last_p = False
                for p_tag in paragraphs:
                    if p_tag.name != "p":
                        jp_text_collection.append((p_tag.get_text(), p_tag.name))
                        last_p = False
                    elif last_p:
                        text, tag = jp_text_collection[-1]
                        jp_text_collection[-1] = (text + '\n' + p_tag.get_text(), tag)
                    else:
                        jp_text_collection.append((p_tag.get_text(), p_tag.name))
                        last_p = True
                        
                for jp_texts, name in jp_text_collection:
                    # Handle paragraph
                    if name == "p":
                        # Modify chapter_text using change function
                        jp_text_parts = split_string_by_length(jp_texts, config["MAX_LENGTH"])
                        for jp_text in jp_text_parts:
                            
                            # Remove images
                            img_pattern = re.compile(r'<img[^>]+>')
                            jp_text = img_pattern.sub('', jp_text)
                            jp_text = concat_kanji_rubi(jp_text)
                            
                            # Remove first line if contain title and 作
                            first_line = jp_text.strip().split("\n")[0].strip()
                            if "作" in first_line and re.sub(
                                r"\s", "", config["JP_TITLE"]
                            ) in re.sub(r"\s", "", first_line):
                                jp_text = jp_text.replace(first_line + '\n', '')

                            if len(jp_text.strip()) != 0:
                                ### Start translation
                                if chapterwise:
                                    result[item.id].append(jp_text)
                                else:
                                    result.append(jp_text)
                                ### Translation finished
                                
            if chapterwise:
                if not result[item.id]:
                    del result[item.id]

    return result
        

if __name__ == "__main__":
    config = load_config()
    print(main(f"output/{config['CN_TITLE']}/input.epub"))
