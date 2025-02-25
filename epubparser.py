from ebooklib import epub
from bs4 import BeautifulSoup
import re
from tqdm import tqdm
from utils import split_string_by_length, load_config, concat_kanji_rubi, get_filtered_tags


def clean_html_content(html_content, config):
    """
    Clean and process HTML content by removing specific tags and extracting text.
    
    Args:
        html_content (str): HTML content to process
        config (dict): Configuration dictionary
        
    Returns:
        BeautifulSoup: Cleaned soup object
    """
    soup = BeautifulSoup(html_content, "html5lib")
    
    # Remove ruby annotations
    for rt_tag in soup.find_all("rp"):
        rt_tag.decompose()
    for rt_tag in soup.find_all("rt"):
        rt_tag.decompose()
        
    return soup


def extract_paragraphs(soup):
    """
    Extract paragraphs and headings from a BeautifulSoup object.
    
    Args:
        soup (BeautifulSoup): Parsed HTML
        
    Returns:
        list: Collection of text segments with their tag information
    """
    if not soup.body.find(["p", "h1", "h2", "h3", "h4", "h5", "h6"]):
        return []
    
    paragraphs = get_filtered_tags(soup)
    
    # Get consecutive paragraphs and titles
    text_collection = []
    last_p = False
    
    for p_tag in paragraphs:
        if len(p_tag.get_text()) == 0:
            continue
        if p_tag.name != "p":
            text_collection.append((p_tag.get_text(), p_tag.name))
            last_p = False
        elif last_p:
            text, tag = text_collection[-1]
            text_collection[-1] = (text + '\n' + p_tag.get_text(), tag)
        else:
            text_collection.append((p_tag.get_text(), p_tag.name))
            last_p = True
            
    return text_collection


def process_text_segments(text_collection, config):
    """
    Process text segments, clean them and prepare for translation.
    
    Args:
        text_collection (list): List of (text, tag_name) tuples
        config (dict): Configuration dictionary
        
    Returns:
        list: Processed text segments ready for translation
    """
    processed_segments = []
    
    for text, tag_name in text_collection:
        # Currently only processing paragraph tags
        if tag_name == "p":
            # Split long text
            text_parts = split_string_by_length(text, config["MAX_LENGTH"])
            
            for part in text_parts:
                # Remove images
                img_pattern = re.compile(r'<img[^>]+>')
                cleaned_text = img_pattern.sub('', part)
                cleaned_text = concat_kanji_rubi(cleaned_text)
                
                # Remove first line if it contains title and 作
                lines = cleaned_text.strip().split("\n")
                if lines:
                    first_line = lines[0].strip()
                    jp_title_clean = re.sub(r"\s", "", config["JP_TITLE"])
                    if "作" in first_line and jp_title_clean in re.sub(r"\s", "", first_line):
                        cleaned_text = cleaned_text.replace(first_line + '\n', '')

                if len(cleaned_text.strip()) != 0:
                    processed_segments.append(cleaned_text)
    
    return processed_segments


def process_html_content(html_content, config):
    """
    Process any HTML content and extract cleaned text segments.
    
    Args:
        html_content (str): HTML content to process
        config (dict): Configuration dictionary
        
    Returns:
        list: Processed text segments
    """
    soup = clean_html_content(html_content, config)
    text_collection = extract_paragraphs(soup)
    return process_text_segments(text_collection, config)


def process_epub_file(book_name, chapterwise=False):
    """
    Process an EPUB file and extract text content.
    
    Args:
        book_name (str): Path to the EPUB file
        chapterwise (bool): Whether to organize results by chapter
        
    Returns:
        dict or list: Extracted text content
    """
    if chapterwise:
        result = {}
    else:
        result = []

    config = load_config()
    book = epub.read_epub(book_name, {"ignore_ncx": False})

    # Process chapters and TOCs
    for item in tqdm(list(book.get_items())):
        if (
            isinstance(item, epub.EpubHtml)
            and not isinstance(item, epub.EpubNav)
            and "TOC" not in item.id
            and "toc" not in item.id
        ):

            html_content = item.content.decode("utf-8")
            processed_segments = process_html_content(html_content, config)

            if processed_segments:
                if chapterwise:
                    result[item.id] = processed_segments
                else:
                    result.extend(processed_segments)

    # Clean up empty chapters if needed
    if chapterwise:
        result = {k: v for k, v in result.items() if v}

    return result


def main(book_name, chapterwise=False):
    """
    Main function to process an EPUB book.
    
    Args:
        book_name (str): Path to the EPUB file
        chapterwise (bool): Whether to organize results by chapter
        
    Returns:
        dict or list: Extracted text content
    """
    return process_epub_file(book_name, chapterwise)


if __name__ == "__main__":
    config = load_config()
    print(main(f"output/{config['CN_TITLE']}/input.epub"))
