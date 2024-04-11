import pprint
import lxml.html
import lxml.html.clean
import os

from .errors import PreprocessorError
from .responses import Response, ScrapeResponse
from .apicall import OpenAiCall, Postprocessor, RetryRule
from .utils import logger, _tokens, _tostr


class SchemaScrapper(OpenAiCall):

    def __init__(
      self, 
      schema: dict | str | list,
      *, 
      models: list[str] = ["gpt-3.5-turbo", "gpt-4-turbo-preview"],
      model_params: dict | None = None,
      max_cost: float = 1,
      retry: RetryRule = RetryRule(1, 30),
      extra_instructions: list[str] | None = None,
      postprocessors: list | None = None,
      promt_file_name: str = "text_promt.md"
   ):
      super().__init__(
          models=models, 
          model_params=model_params, 
          max_cost=max_cost, 
          extra_instructions=extra_instructions, 
          postprocessors=postprocessors, 
          retry=retry
      )

      # Read instructions from a Markdown file
      promt_directory = os.path.join(os.getcwd(), "promts")
      with open(os.path.join(promt_directory, promt_file_name), 'r') as file:
        instructions = file.read()

      # Insert the schema parameter into the instructions
      instructions_formatted = instructions.format(schema=schema)

      self.system_messages = [instructions_formatted]

      # self.system_messages = [
      #   f"For the given HTML, convert to a JSON file matching this schema: "
      #   f"{schema}",
      #   "Limit responses to valid JSON, with no explanatory text. "
      #   "Never truncate the JSON with an ellipsis. "
      #   "Always use double quotes for strings and escape quotes with \\. "
      #   "Always omit trailing commas. ",
      # ]

  
    def scrape(
         self,
         html
    ) -> Response:
      sr = ScrapeResponse()
      response = self._api_request(html)
      return response

    def vision_scrape(self, html: str, img_url: str) -> Response:
        return self._vision_api_request(img_url, html)
    
    __call__ = scrape


