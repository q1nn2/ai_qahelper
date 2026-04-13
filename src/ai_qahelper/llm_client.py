from __future__ import annotations

import json
import os
from typing import TypeVar

from openai import OpenAI
from pydantic import BaseModel

from ai_qahelper.models import LlmConfig

T = TypeVar("T", bound=BaseModel)


class LlmClient:
    def __init__(self, config: LlmConfig) -> None:
        api_key = (config.api_key or "").strip() or os.getenv(config.api_key_env)
        if not api_key:
            raise RuntimeError(
                f"Missing API key: set llm.api_key in ai-tester.config.yaml or env var {config.api_key_env}"
            )
        self._client = OpenAI(base_url=config.base_url, api_key=api_key)
        self._model = config.model
        self._temperature = config.temperature

    def complete_json(self, system_prompt: str, user_prompt: str, schema: type[T]) -> T:
        response = self._client.responses.create(
            model=self._model,
            temperature=self._temperature,
            input=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        text = response.output_text
        parsed = json.loads(text)
        return schema.model_validate(parsed)
