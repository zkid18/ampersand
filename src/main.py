import os
import json
import time
import pprint
import random
from typing import Any, Sequence, List, Iterator, cast
from contextlib import contextmanager

import boto3
import gspread
import requests
from bs4 import BeautifulSoup
from botocore.exceptions import NoCredentialsError
from oauth2client.service_account import ServiceAccountCredentials
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.common.exceptions import WebDriverException
from webdriver_manager.chrome import ChromeDriverManager

from .openai_scrrapper import SchemaScrapper

@contextmanager
def get_webdriver():
    options = Options()
    options.add_argument("--no-sandbox")  # Bypass OS security model, REQUIRED for Docker
    options.add_argument("--headless")  # Run in headless mode
    options.add_argument("--disable-dev-shm-usage")  # Overcome limited resource problems
    options.add_argument("--disable-gpu")  # Applicable to windows os only
    options.add_argument("--disable-extensions")
    options.add_argument("--remote-debugging-port=9222")  # Th
    
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    
    try:
        yield driver
    finally:
        driver.quit()

def read_google_sheets(sheet_url, range_name):
    # Define the scope of the application
    scope = ['https://spreadsheets.google.com/feeds','https://www.googleapis.com/auth/drive']

    # Add credentials to the account
    creds = ServiceAccountCredentials.from_json_keyfile_name('./credentials/client_secret.json', scope)

    # Authorize the clientsheet 
    client = gspread.authorize(creds)

    # Open the sheet
    sheet = client.open_by_url(sheet_url).sheet1

    # Get all records of the data
    data = sheet.get(range_name)
    return data


def check_websites_accessible(websites):
    inaccessible_websites = []
    for website in websites:
        # Ensure the website starts with http:// or https://
        if not website.startswith(('http://', 'https://')):
            website = 'https://' + website
        # Ensure the website includes www if it doesn't have a subdomain
        if "://" in website and not website.split("://")[1].startswith("www."):
            website = website.split("://")[0] + "://www." + website.split("://")[1]
        
        # Append "/pricing" to the URL
        website_with_pricing = website.rstrip('/') + '/pricing'

        try:
            response = requests.get(website_with_pricing, timeout=10)
            if response.status_code != 200:
                # If the status code is not in the 200-299 range, add to the list
                inaccessible_websites.append(website)
        except requests.RequestException:
            # If there's an error (e.g., timeout, DNS failure), consider it inaccessible
            inaccessible_websites.append(website)
    return inaccessible_websites


@staticmethod
def remove_unwanted_tags(html_content: str, unwanted_tags: List[str]) -> str:
    """
    Remove unwanted tags from a given HTML content.

    Args:
        html_content: The original HTML content string.
        unwanted_tags: A list of tags to be removed from the HTML.

    Returns:
        A cleaned HTML string with unwanted tags removed.
    """
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html_content, "html.parser")
    for tag in unwanted_tags:
        for element in soup.find_all(tag):
            element.decompose()
    return str(soup)


@staticmethod
def get_tags(html_content: str, tags: List[str]) -> str:
    """
    Extract specific tags from a given HTML content.

    Args:
        html_content: The original HTML content string.
        tags: A list of tags to be extracted from the HTML.

    Returns:
        A string combining the content of the extracted tags.
    """

    soup = BeautifulSoup(html_content, "html.parser")
    text_parts: List[str] = []
    for element in soup.find_all():
        if element.name in tags:
            # Extract all navigable strings recursively from this element.
            text_parts += get_navigable_strings(element)

            # To avoid duplicate text, remove all descendants from the soup.
            element.decompose()

    return " ".join(text_parts)

@staticmethod
def remove_unnecessary_lines(content: str) -> str:
    """
    Clean up the content by removing unnecessary lines.

    Args:
        content: A string, which may contain unnecessary lines or spaces.

    Returns:
        A cleaned string with unnecessary lines removed.
    """
    lines = content.split("\n")
    stripped_lines = [line.strip() for line in lines]
    non_empty_lines = [line for line in stripped_lines if line]
    cleaned_content = " ".join(non_empty_lines)
    return cleaned_content


def get_navigable_strings(element: Any) -> Iterator[str]:
    """Get all navigable strings from a BeautifulSoup element.

    Args:
        element: A BeautifulSoup element.

    Returns:
        A generator of strings.
    """

    from bs4 import NavigableString, Tag

    for child in cast(Tag, element).children:
        if isinstance(child, Tag):
            yield from get_navigable_strings(child)
        elif isinstance(child, NavigableString):
            if (element.name == "a") and (href := element.get("href")):
                yield f"{child.strip()} ({href})"
            else:
                yield child.strip()


def transform_documents(
    raw_html: str,
    unwanted_tags: List[str] = ["script", "style", "a", "img"],
    tags_to_extract: List[str] = ["p", "li", "div"],
    extract_tags: bool = True,
    remove_lines: bool = True,
    **kwargs: Any,
) -> Sequence[str]:
    """
    Transform a list of Document objects by cleaning their HTML content.

    Args:
        documents: A str object containing HTML content.
        unwanted_tags: A list of tags to be removed from the HTML.
        tags_to_extract: A list of tags whose content will be extracted.
        remove_lines: If set to True, unnecessary lines will be
        removed from the HTML content.

    Returns:
        A sequence of Document objects with transformed content.
    """
    cleaned_content = remove_unwanted_tags(raw_html, unwanted_tags)

    if extract_tags:
        cleaned_content = get_tags(cleaned_content, tags_to_extract)

    if remove_lines:
        cleaned_content = remove_unnecessary_lines(cleaned_content)

    return cleaned_content


def parse_page(driver, website):
    # Ensure the website starts with http:// or https://
    if not website.startswith(('http://', 'https://')):
        website = 'https://' + website
    # Ensure the website includes www if it doesn't have a subdomain
    if "://" in website and not website.split("://")[1].startswith("www."):
        website = website.split("://")[0] + "://www." + website.split("://")[1]
    
    # Append "/pricing" to the URL
    website_with_pricing = website.rstrip('/') + '/pricing'

    # Format the filename as 'websiteName_YYYY-MM-DD.png'
    timestamp = time.strftime("%Y-%m-%d")
    html_directory = os.path.join(os.getcwd(), "html")
    html_filename = os.path.join(html_directory, f"{website.split('//')[-1].split('/')[0]}_{timestamp}.html")
    
    img_directory = os.path.join(os.getcwd(), "img")
    img_filename = os.path.join(img_directory, f"{website.split('//')[-1].split('/')[0]}_{timestamp}.png")
    import logging

    try: 
        logging.info(f"accessing the page {website_with_pricing}")
        driver.get(website_with_pricing)
    except WebDriverException:
        logging.error(f"page is down for {website_with_pricing}")

    html = driver.page_source
    with open(html_filename, 'w', encoding='utf-8') as file:
        file.write(html)
    
    # html_transformed = transform_documents(raw_html=html, tags_to_extract=["div","span","h2"], extract_tags=False)
    html_transformed = transform_documents(raw_html=html, extract_tags=False)

     # Retrieve the dimensions of the page to capture the full page
    total_width = driver.execute_script("return document.body.offsetWidth")
    total_height = driver.execute_script("return document.body.scrollHeight")
    
    # Set window size to page size
    driver.set_window_size(total_width, total_height)
    driver.save_screenshot(img_filename)

    # upload_to_digitalocean_space(img_filename)
    return img_filename, html_filename, html_transformed


def load_schema(schema_file_path):
    with open(schema_file_path, 'r') as file:
        schema = json.load(file)
    return schema


def upload_to_digitalocean_space(file_name, bucket_name="pricing", object_name=None):
    """
    Upload a file to a DigitalOcean Space
    :param file_name: File to upload
    :param bucket_name: Bucket to upload to
    :param object_name: S3 object name. If not specified, file_name is used
    :return: True if file was uploaded, else False
    """
    
    # If S3 object_name was not specified, use file_name
    if object_name is None:
        object_name = file_name

    # Your DigitalOcean Spaces keys
    access_key = os.environ.get('DO_SPACES_ACCESS_KEY')
    secret_key = os.environ.get('DO_SPACES_SECRET_KEY')
    endpoint_url = os.environ.get('DO_ENDPOINT_URL')

    # Initialize a session using DigitalOcean Spaces.
    session = boto3.session.Session()
    client = session.client('s3',
                            region_name='sfo3',
                            endpoint_url=endpoint_url,
                            aws_access_key_id=access_key,
                            aws_secret_access_key=secret_key)

    try:
        client.upload_file(file_name, bucket_name, object_name)
        print(f"File {file_name} uploaded to {bucket_name}/{object_name}.")
        return True
    except NoCredentialsError:
        print("Credentials not available")
        return False



if __name__ == "__main__":
  # Example usage
  sheet_url = 'https://docs.google.com/spreadsheets/d/1KvsDGP-7dibeRVSM2Wz_T1ZbllYx2bzpZpaRGx_6xxY/edit#gid=79839392'
  range_name = 'A:P'
  sheet_data = read_google_sheets(sheet_url, range_name)
  column_index = 14
  website_column_data = [row[column_index] for row in sheet_data if len(row) > column_index]

  schema_path = 'schema/main_schema.json'
  schema = load_schema(schema_path)


  with get_webdriver() as driver:
    website = website_column_data[2]
    img_filename, html_filename, html_transformed = parse_page(driver, website)

    scrapper = SchemaScrapper(schema)
    response = scrapper.scrape(html_transformed)
    pprint.pprint(response.data)

    vision_scrapper = SchemaScrapper(schema, promt_file_name="text_image_promt.md")
    img_url = "https://pricing.sfo3.digitaloceanspaces.com/pricing/www.sprig.com_2024-03-21.png"
    response = vision_scrapper.vision_scrape(html_transformed, img_url)
    pprint.pprint(response.data)

