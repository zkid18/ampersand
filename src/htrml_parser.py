import logging
import os
import time
from typing import Any, Iterator, List, Sequence, cast

from bs4 import BeautifulSoup, NavigableString, Tag
from selenium.common.exceptions import WebDriverException



class Parser:
    def __init__(self, website: str, driver, unwanted_tags: List[str] = None, tags_to_extract: List[str] = None):
        self.website = website
        self.driver = driver
        self.unwanted_tags = unwanted_tags if unwanted_tags is not None else ["script", "style", "a", "img"]
        self.tags_to_extract = tags_to_extract if tags_to_extract is not None else ["p", "li", "div"]


    def parse_page(self):
        website = self._ensure_website_format(self.website)
        timestamp = time.strftime("%Y-%m-%d")

        html_directory = os.path.join(os.getcwd(), "html")
        html_filename = os.path.join(html_directory, f"{website.split('//')[-1].split('/')[0]}_{timestamp}.html")
        html_transformed_filename = os.path.join(html_directory, f"{website.split('//')[-1].split('/')[0]}_{timestamp}_transformed.html")
        
        img_directory = os.path.join(os.getcwd(), "img")
        img_filename = os.path.join(img_directory, f"{website.split('//')[-1].split('/')[0]}_{timestamp}.png")

        try: 
            logging.info(f"Accessing the page {website}")
            self.driver.get(website)
        except WebDriverException:
            logging.error(f"Page is down for {website}")
            return None

        html = self.driver.page_source
        with open(html_filename, 'w', encoding='utf-8') as file:
            file.write(html)
        
        html_transformed = self._transform_documents(raw_html=html, extract_tags=False)
        with open(html_transformed_filename, 'w', encoding='utf-8') as file:
            file.write(html_transformed)

        total_width = self.driver.execute_script("return document.body.offsetWidth")
        total_height = self.driver.execute_script("return document.body.scrollHeight")
        
        self.driver.set_window_size(total_width, total_height)
        self.driver.save_screenshot(img_filename)

        return img_filename, html_filename, html_transformed

    def _ensure_website_format(self, website: str) -> str:
        if not website.startswith(('http://', 'https://')):
            website = 'https://' + website
        if "://" in website and not website.split("://")[1].startswith("www."):
            website = website.split("://")[0] + "://www." + website.split("://")[1]
        return website

    def _remove_unwanted_tags(self, html_content: str) -> str:
        soup = BeautifulSoup(html_content, "html.parser")
        for tag in self.unwanted_tags:
            for element in soup.find_all(tag):
                element.decompose()
        return str(soup)

    def _get_tags(self, html_content: str) -> str:
        soup = BeautifulSoup(html_content, "html.parser")
        text_parts: List[str] = []
        for tag in self.tags_to_extract:
            for element in soup.find_all(tag):
                text_parts.append(element.get_text(strip=True))
        return " ".join(text_parts)

    def _remove_unnecessary_lines(self, content: str) -> str:
        lines = content.split("\n")
        stripped_lines = [line.strip() for line in lines]
        non_empty_lines = [line for line in stripped_lines if line]
        cleaned_content = " ".join(non_empty_lines)
        return cleaned_content


    def _transform_documents(self, raw_html: str, extract_tags: bool = True, remove_lines: bool = True) -> str:
        cleaned_content = self._remove_unwanted_tags(raw_html)

        if extract_tags:
            cleaned_content = self._get_tags(cleaned_content)

        if remove_lines:
            cleaned_content = self._remove_unnecessary_lines(cleaned_content)

        return cleaned_content