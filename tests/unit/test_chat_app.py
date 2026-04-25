from __future__ import annotations

from ai_qahelper.chat_app import SUPPORTED_UPLOAD_TYPES


def test_supported_upload_types_include_word_and_excel() -> None:
    assert {"docx", "xlsx", "xls"}.issubset(SUPPORTED_UPLOAD_TYPES)
