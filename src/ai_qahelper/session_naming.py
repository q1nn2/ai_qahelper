from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

# Windows: \ / : * ? " < > |
_INVALID_FS_CHARS = re.compile(r'[\\/:*?"<>|]+')
_SLUG_COLLAPSE = re.compile(r"_+")

_MAX_SLUG_LEN = 48


def _sanitize_slug_part(raw: str) -> str:
    s = _INVALID_FS_CHARS.sub("_", (raw or "").strip())
    s = _SLUG_COLLAPSE.sub("_", s).strip("_")
    if len(s) > _MAX_SLUG_LEN:
        s = s[:_MAX_SLUG_LEN].rstrip("_")
    return s or "session"


def _slug_from_target_url(target_url: str) -> str:
    netloc = urlparse(target_url).netloc or "unknown-host"
    host = netloc.split("@", 1)[-1]
    host = host.replace(":", "_")
    return _sanitize_slug_part(host.replace(".", "_"))


def _slug_from_requirements(local_paths: list[str]) -> str | None:
    for p in local_paths:
        stem = Path(p).stem.strip()
        if stem:
            return _sanitize_slug_part(stem)
    return None


def build_session_id(
    *,
    created_at: datetime,
    target_url: str,
    local_requirement_paths: list[str],
    session_label: str | None = None,
) -> str:
    """
    Человекочитаемый id папки: YYYY-MM-DD_HH-MM-SS_<slug>_<6hex>.
    created_at — обычно UTC.
    """
    ts = created_at.strftime("%Y-%m-%d_%H-%M-%S")
    if session_label and session_label.strip():
        slug = _sanitize_slug_part(session_label.strip())
    else:
        slug = _slug_from_requirements(local_requirement_paths) or _slug_from_target_url(target_url)
    suffix = uuid4().hex[:6]
    return f"{ts}_{slug}_{suffix}"
