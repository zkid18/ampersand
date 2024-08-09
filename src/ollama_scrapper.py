import os

from src.errors import PreprocessorError
from src.responses import Response, ScrapeResponse
from src.ollamacall import OllamaCall
from src.apicall import OpenAiCall, Postprocessor, RetryRule
from src.utils import logger, _tokens, _tostr


class SchemaScrapper(OllamaCall):

    def __init__(
      self, 
      schema: dict or str or list,
      promt_file_name: str,
      *, 
      models: list[str] = ["mistral"],
      model_params: dict or None = None,
      max_cost: float = 1,
      retry: RetryRule = RetryRule(1, 30),
      extra_instructions: list[str] or None = None,
      postprocessors: list or None = None
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
      promt_directory = os.path.join(os.getcwd())
      with open(os.path.join(promt_directory, promt_file_name), 'r') as file:
        instructions = file.read()

      # Insert the schema parameter into the instructions
      instructions_formatted = instructions.format(schema=schema)

      self.system_messages = [instructions_formatted]
  
    def scrape(
         self,
         html
    ) -> Response:
      sr = ScrapeResponse()
      response = self._api_request(html)
      return response
    
    __call__ = scrape


