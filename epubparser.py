from ebooklib import epub
from bs4 import BeautifulSoup
import re
from tqdm import tqdm
from utils import split_string_by_length, remove_leading_numbers
import re


def main(book_name):
    result = []
    
    # Open the EPUB file
    book = epub.read_epub(book_name, {"ignore_ncx": False})

    ############ Translate the chapter titles ############
    ncx = book.get_item_with_id("ncx")
    if ncx is not None:
        content = ncx.content.decode("utf-8")
        soup = BeautifulSoup(content, "html5lib")
        navpoints = soup.find_all("navpoint")
        output = ""
        jp_titles = []
        for i, navpoint in enumerate(navpoints):
            name = navpoint.find('text').get_text(strip=True)
            output += str(i) + " " + name + "\n"
            jp_titles.append(name)
        jp_titles_parts = split_string_by_length(output)
        
        # Traverse the aggregated chapter titles
        for jp_text in jp_titles_parts:
            jp_text = '、'.join([remove_leading_numbers(s) for s in jp_text.split('\n')])
            result.append(jp_text)

    ############ Translate the chapters and TOCs ############
    for item in tqdm(list(book.get_items())):
        
        if isinstance(item, epub.EpubHtml) and not isinstance(item, epub.EpubNav) \
        and "TOC" not in item.id and "toc" not in item.id:
            # Parse HTML and extract text
            soup = BeautifulSoup(item.content.decode("utf-8"), "html5lib")
            
            for rt_tag in soup.find_all("rt"):
                rt_tag.decompose()
            
            if soup.body.find('p'):
                # Extract paragraphs and join them with new lines
                paragraphs = soup.find_all(["p", "img"])
                jp_texts = "\n".join([p.get_text() if p.name == "p" else str(p) for p in paragraphs])
                
                # Modify chapter_text using change function
                jp_text_parts = split_string_by_length(jp_texts)
                for jp_text in jp_text_parts:
                    # Remove images
                    img_pattern = re.compile(r'<img[^>]+>\n')
                    jp_text = img_pattern.sub('', jp_text)
                    result.append(jp_text)
                    
    # with open('book.pkl', 'wb') as f:
    #     pickle.dump(result, f)

    return result
        

if __name__ == "__main__":
    main("input.epub")
