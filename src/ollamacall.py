"""
Module for making OpenAI API calls.
"""
import ollama
from dataclasses import dataclass
from typing import Callable

from src.errors import (
    ScrapeghostError,
    TooManyTokens,
    MaxCostExceeded,
    BadStop,
)
from src.responses import Response
from src.utils import (
    logger,
    _tokens,
)
from src.models import _model_dict


@dataclass
class RetryRule:
    max_retries: int = 0
    retry_wait: int = 30  # seconds


class OllamaCall:

    def __init__(
        self,
        *,
        # OpenAI parameters
        models: list[str] = ["mistral"],
        model_params: dict or None = None,
        max_cost: float = 1,
        # instructions
        extra_instructions: list[str] or None = None,
        postprocessors: list or None = None,
        # retry rules
        retry: RetryRule = RetryRule(1, 30),
    ):
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
        self.total_cost: float = 0
        self.max_cost = max_cost
        self.models = models
        self.retry = retry
        if model_params is None:
            model_params = {}
        self.model_params = model_params
        # default temperature to 0, deterministic
        if "temperature" not in model_params:
            model_params["temperature"] = 0

        self.system_messages = []
        if extra_instructions:
            self.system_messages.extend(extra_instructions)

    def _api_request(self, html: str) -> Response:
        model = self.models[0]
        response = Response()
        self._raw_api_request(
            model=model,
            messages=[
                {"role": "system", "content": msg}
                for msg in self.system_messages
            ]
            + [
                {"role": "user", "content": html},
            ],
            response=response,
        )
        return response

    def _raw_api_request(
        self,
        model: str,
        messages: list[dict[str, str]],
        response: Response,
    ) -> Response:
        """
        Make an Ollama request and return the raw response.

        * model - the OpenAI model to use
        * messages - the messages to send to the API
        * response - the Response object to augment

        Augments the response object with the API response, prompt tokens,
        completion tokens, and cost.
        """
        completion = ollama.chat(
            model=model,
            format="json",
            messages=messages,
            options=ollama.Options(
                temperature=0.0,
                num_ctx=100000,
                num_predict=-1,
            ),
        )

        response.data = completion["message"]["content"]  # type: ignore
        return response

    def _apply_postprocessors(self, response: Response) -> Response:
        for pp in self.postprocessors:
            logger.debug(
                "postprocessor",
                postprocessor=str(pp),
                data=response.data,
                data_type=type(response.data),
            )
            response = pp(response, self)
        return response


    def stats(self) -> dict:
        """
        Return stats about the scraper.
        """
        return {
            "total_prompt_tokens": self.total_prompt_tokens,
            "total_completion_tokens": self.total_completion_tokens,
            "total_cost": self.total_cost,
        }