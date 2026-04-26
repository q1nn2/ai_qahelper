from __future__ import annotations

import pytest

from ai_qahelper.llm_client import _extract_json_text, _parse_json_payload
from ai_qahelper.llm_errors import LlmJsonParseError


def test_extract_json_from_markdown_fence() -> None:
    raw = """Here is JSON:
```json
{"a": 1}
```
"""
    assert _extract_json_text(raw).strip() == '{"a": 1}'


def test_parse_json_payload_object() -> None:
    data = _parse_json_payload('{"x": true}')
    assert data == {"x": True}


def test_parse_json_invalid_raises() -> None:
    with pytest.raises(LlmJsonParseError):
        _parse_json_payload("not json at all {{{")
