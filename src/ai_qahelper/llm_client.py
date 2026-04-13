from __future__ import annotations

import base64
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
        return text[start_arr : text.rfind("]") + 1]
    return text[start_obj : text.rfind("}") + 1]


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
                f"Missing API key: set llm.api_key in ai-tester.config.yaml, "
                f"env var {config.api_key_env}, or a .env file in the project root with {config.api_key_env}=..."
            )
        timeout = float(config.request_timeout_seconds)
        self._client = OpenAI(base_url=config.base_url, api_key=api_key, timeout=timeout)
        self._model = config.model
        self._vision_model = (config.vision_model or "").strip() or "gpt-4o-mini"
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
            "OpenAI responses.create: model=%s timeout=%s",
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

    def describe_pdf_pages_for_requirements(
        self,
        page_pngs: list[tuple[int, bytes]],
        *,
        pages_per_batch: int = 2,
        max_output_tokens: int = 4096,
    ) -> str:
        """
        Описание визуала страниц PDF для последующего тест-анализа (Chat Completions + vision).
        page_pngs: (номер страницы с 1, PNG bytes).
        """
        if not page_pngs:
            return ""

        system = (
            "Ты помощник QA. По скриншотам страниц PDF опиши на русском всё важное для тестирования: "
            "макеты, формы, подписи полей, кнопки, таблицы, диаграммы, нумерацию разделов, тексты на картинках. "
            "Не придумывай то, что не видно. Структурируй по страницам (Страница N). "
            "Если страница пустая или нечитаемая — так и напиши."
        )
        parts_out: list[str] = []
        batch_size = max(1, pages_per_batch)
        for start in range(0, len(page_pngs), batch_size):
            chunk = page_pngs[start : start + batch_size]
            first_p, last_p = chunk[0][0], chunk[-1][0]
            user_content: list[dict[str, Any]] = [
                {
                    "type": "text",
                    "text": (
                        f"Страницы PDF {first_p}–{last_p} (изображения ниже). "
                        "Дай структурированное описание для тест-дизайна."
                    ),
                }
            ]
            for page_num, png in chunk:
                b64 = base64.standard_b64encode(png).decode("ascii")
                user_content.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{b64}", "detail": "auto"},
                    }
                )

            logger.info(
                "chat.completions vision: model=%s pages=%s-%s",
                self._vision_model,
                first_p,
                last_p,
            )
            resp = self._client.chat.completions.create(
                model=self._vision_model,
                temperature=min(self._temperature, 0.4),
                max_tokens=max_output_tokens,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_content},
                ],
            )
            choice = resp.choices[0].message.content
            if choice and choice.strip():
                parts_out.append(f"### Страницы {first_p}–{last_p}\n{choice.strip()}")

        return "\n\n".join(parts_out)
