import argparse
import json
import os
from contextlib import contextmanager

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

from src.openai_scrrapper import SchemaScrapper
from src.htrml_parser import Parser
from src.utils import load_schema, upload_to_digitalocean_space

@contextmanager
def get_webdriver():
    options = Options()
    options.add_argument("--no-sandbox")  # Bypass OS security model, REQUIRED for Docker
    options.add_argument("--headless")  # Run in headless mode
    options.add_argument("--disable-dev-shm-usage")  # Overcome limited resource problems
    options.add_argument("--disable-gpu")  # Applicable to windows os only
    options.add_argument("--disable-extensions")
    options.add_argument("--remote-debugging-port=9222")  # Th
    
    driver = webdriver.Chrome(options=options)
    
    try:
        yield driver
    finally:
        driver.quit()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scrape and process a webpage.")
    parser.add_argument("url", help="The URL of the webpage to scrape.")
    parser.add_argument("--schema_path", default='schema/main_schema.json', help="Path to the schema JSON file.")
    parser.add_argument("--prompt_path", default='prompts/text_prompt.md', help="Path to the prompt file for scrapper.")
    parser.add_argument("--use_vision_scrapper", action='store_true', help="Use the vision scrapper instead of the standard scrapper.")
    parser.add_argument("--upload_to_s3", default=False, action='store_true', help="Specify whether to upload files to S3.")
    args = parser.parse_args()

    website = args.url
    schema_path = args.schema_path
    prompt_path = args.prompt_path

    schema = load_schema(schema_path)

    with get_webdriver() as driver:
        html_parser = Parser(driver=driver, website=website)
        img_filename, html_filename, html_transformed = html_parser.parse_page()
        print(html_transformed)
        if args.upload_to_s3:
            img_url = upload_to_digitalocean_space(img_filename)

        if args.use_vision_scrapper:
            vision_scrapper = SchemaScrapper(schema, prompt_path)
            response = vision_scrapper.vision_scrape(html_transformed, img_url)
            scrapper_name = "vision_scrapper"
        else:
            scrapper = SchemaScrapper(schema, prompt_path)
            response = scrapper.scrape(html_transformed)
            scrapper_name = "text_scrapper"
        
        # Save the response data to a JSON file in the /output folder
        output_path = os.path.join('output', f"{website.split('//')[-1].split('/')[0]}_{scrapper_name}_response.json")
        with open(output_path, 'w') as outfile:
            json.dump(response.data, outfile)
            print(f"Response data saved to {output_path}.")

