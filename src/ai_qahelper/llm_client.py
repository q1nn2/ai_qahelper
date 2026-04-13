from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, TypeVar

from openai import APIError, OpenAI
from pydantic import BaseModel

from ai_qahelper.models import LlmConfig

logger = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)


def _extract_json_text(raw: str) -> str:
    text = (raw or "").strip()
    if not text:
        return text
    fence = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL | re.IGNORECASE)
    if fence:
        return fence.group(1).strip()
    if text.startswith("{") or text.startswith("["):
        return text
    start_obj = text.find("{")
    start_arr = text.find("[")
    if start_obj == -1 and start_arr == -1:
        return text
    if start_arr != -1 and (start_obj == -1 or start_arr < start_obj):
        return text[start_arr: text.rfind("]") + 1]
    return text[start_obj: text.rfind("}") + 1]


def _parse_json_payload(text: str) -> Any:
    snippet = _extract_json_text(text)
    try:
        return json.loads(snippet)
    except json.JSONDecodeError as first:
        logger.warning("JSON parse failed (first try): %s", first)
        try:
            start, end = snippet.find("{"), snippet.rfind("}")
            if start != -1 and end > start:
                return json.loads(snippet[start : end + 1])
        except json.JSONDecodeError:
            pass
        raise first


class LlmClient:
    def __init__(self, config: LlmConfig) -> None:
        api_key = (config.api_key or "").strip() or os.getenv(config.api_key_env)
        if not api_key:
            raise RuntimeError(
                f"Missing API key: set llm.api_key in ai-tester.config.yaml or env var {config.api_key_env}"
            )
        timeout = float(config.request_timeout_seconds)
        self._client = OpenAI(base_url=config.base_url, api_key=api_key, timeout=timeout)
        self._model = config.model
        self._temperature = config.temperature
        self._max_output_tokens = config.max_output_tokens

    def complete_json(
        self,
        system_prompt: str,
        user_prompt: str,
        schema: type[T],
        *,
        root_list_key: str | None = None,
    ) -> T:
        kwargs: dict[str, Any] = {
            "model": self._model,
            "temperature": self._temperature,
            "input": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        if self._max_output_tokens > 0:
            kwargs["max_output_tokens"] = self._max_output_tokens

        logger.info(
            "OpenAI responses.create: model=%s timeout=%ss",
            self._model,
            getattr(self._client, "timeout", "?"),
        )
        try:
            response = self._client.responses.create(**kwargs)
        except APIError as err:
            if "max_output_tokens" in kwargs and "max_output_tokens" in str(err).lower():
                logger.warning("Retrying without max_output_tokens: %s", err)
                kwargs.pop("max_output_tokens", None)
                response = self._client.responses.create(**kwargs)
            else:
                raise
        text = response.output_text
        if not (text and text.strip()):
            raise RuntimeError("Empty model response (output_text)")

        parsed = _parse_json_payload(text)
        if isinstance(parsed, list) and root_list_key:
            parsed = {root_list_key: parsed}

        return schema.model_validate(parsed)
