# Ampersand – Visual GPT Website Scraper

## Description

Extract unstructured data such as tables and charts without parsing them by hand.

## Features

- Write the prompt to get the data from the website.
- Specify the output JSON schema.
- Control the cost, the context window, and the number of tokens that the model is used.

### Foolder structure
1. The `schema/` directory contains JSON schema files
2. The `prompts/` directory is intended to store prompt files in Markdown format
3. The `output` directory storing the results of the scraping proces

## Installation
1. Install the requirements.txt by running `pip install -r requirements.txt`.
2. Export the environment variables.
3. This project uses Selenium for web scraping.  You need to install the appropriate WebDriver for your browser.

## Run the project
Navigate to the project's root directory in your terminal. Run the project by executing the main.py script with the necessary arguments. Here is an example command: 
`python3 main.py "example.com" --use_vision_scrapper --schema_path "schema/main_schema.json" --prompt_path "prompts/text_image_prompt.md"`

### Arguments description: 

1. `--url`

This is the target website URL from which you want to scrape data. Replace "example.com" with the actual URL of the website you're interested in scraping. Ensure to include the full URL (e.g., https://www.example.com).

2. `--use_vision_scrapper`

This flag indicates that the vision-based scraper should be used. The vision scraper is designed to handle more complex scraping tasks, such as extracting data from images or charts, by utilizing visual recognition techniques.

3. `--schema_path "schema/main_schema.json"`

Specifies the path to the JSON schema file. This schema defines the structure of the output data you expect from the scraper. The path "schema/main_schema.json" should be replaced with the actual path to your JSON schema file. This file dictates how the scraped data is organized and validated.

4. `--prompt_path "prompts/text_image_prompt.md"`

Indicates the path to the prompt file. This file contains instructions or prompts that guide the scraping process, especially useful when using AI models to interpret or extract data from complex web pages. Replace "prompts/text_image_prompt.md" with the path to your specific prompt file.
These arguments allow you to customize the scraping process according to your specific needs, from the target website to the structure of the extracted data and the instructions for handling complex data extraction tasks.

## To-do
The project is still a work in progress (have you seen the non-WIP project?) so it needs to be polished before the 0.0.1 "release".
Note that I use Selenium to grab the screenshot, so you have to install it as well. Later, I consider containerizing the infrastructure.