import json
import os

import boto3
import gspread
import lxml.html
import requests
import structlog
from botocore.exceptions import NoCredentialsError
from oauth2client.service_account import ServiceAccountCredentials

from src.models import _model_dict
import tiktoken


logger = structlog.get_logger("scrapeghost")


def _tostr(obj: lxml.html.HtmlElement) -> str:
    """
    Given lxml.html.HtmlElement, return string
    """
    return lxml.html.tostring(obj, encoding="unicode")


def _tokens(model: str, html: str) -> int:
    encoding = tiktoken.encoding_for_model(model)
    return len(encoding.encode(html))


def cost_estimate(html: str, model: str = "gpt-4") -> float:
    """
    Given HTML, return cost estimate in dollars.

    This is a very rough estimate and not guaranteed to be accurate.
    """
    tokens = _tokens(model, html)
    model_data = _model_dict[model]
    # assumes response is half as long as prompt, which is probably wrong
    return model_data.cost(tokens, tokens // 2)

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


def upload_to_digitalocean_space(file_name, object_name=None):
    """
    Upload a file to a DigitalOcean Space
    :param file_name: File to upload
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
    bucket_name = os.environ.get('DO_SPACES_BUCKET')

    # Initialize a session using DigitalOcean Spaces.
    session = boto3.session.Session()
    client = session.client('s3',
                            region_name='sfo3',
                            endpoint_url=endpoint_url,
                            aws_access_key_id=access_key,
                            aws_secret_access_key=secret_key)

    try:
        client.upload_file(file_name, bucket_name, object_name, ExtraArgs={'ACL': 'public-read'})
        file_url = f"{endpoint_url}/{bucket_name}/{object_name}"
        print(f"File {file_name} uploaded to {file_url}.")
        return file_url
    except NoCredentialsError:
        print("Credentials not available")
        return False


def load_schema(schema_file_path):
    with open(schema_file_path, 'r') as file:
        schema = json.load(file)
    return schema