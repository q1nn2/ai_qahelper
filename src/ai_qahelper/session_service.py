from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

from ai_qahelper.config import load_config
from ai_qahelper.inputs import ingest_figma, parse_requirement_url, parse_requirements
from ai_qahelper.logging_utils import configure_logging
from ai_qahelper.models import SessionState, UnifiedRequirementModel
from ai_qahelper.reporting import save_json
from ai_qahelper.session_naming import build_session_id

logger = logging.getLogger(__name__)


def _session_root() -> Path:
    cfg = load_config()
    root = Path(cfg.sessions_dir)
    root.mkdir(parents=True, exist_ok=True)
    return root


def session_path(session_id: str) -> Path:
    return _session_root() / session_id


def session_file(session_id: str) -> Path:
    return session_path(session_id) / "session.json"


def load_session(session_id: str) -> SessionState:
    return SessionState.model_validate_json(session_file(session_id).read_text(encoding="utf-8"))


def save_session(state: SessionState) -> None:
    path = session_file(state.session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(state.model_dump_json(indent=2), encoding="utf-8")


def retry_attempts(attempts: int, fn):
    last_error = None
    for i in range(attempts):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if i < attempts - 1:
                time.sleep(1 + i)
    raise RuntimeError(f"Operation failed after {attempts} attempts: {last_error}") from last_error


def ingest(
    requirements: list[str],
    requirement_urls: list[str],
    figma_file_key: str | None,
    target_url: str,
    *,
    session_label: str | None = None,
) -> str:
    now = datetime.now(UTC)
    session_id = build_session_id(
        created_at=now,
        target_url=target_url,
        local_requirement_paths=requirements,
        session_label=session_label,
    )
    sdir = session_path(session_id)
    configure_logging(sdir)

    cfg_ingest = load_config()
    allowed = [urlparse(e.base_url.unicode_string()).netloc for e in cfg_ingest.envs]
    target_netloc = urlparse(target_url).netloc
    if allowed and target_netloc not in allowed:
        raise RuntimeError(f"Target URL '{target_url}' is not in allowed environments: {allowed}")

    input_coverage_path = sdir / "input-coverage-report.json"
    req_items = (
        parse_requirements(
            requirements,
            cfg_ingest,
            coverage_report_path=input_coverage_path,
            session_dir=sdir,
        )
        if requirements
        else []
    )
    req_items.extend(parse_requirement_url(url) for url in requirement_urls)

    design = retry_attempts(2, lambda: ingest_figma(figma_file_key)) if figma_file_key else None
    unified = UnifiedRequirementModel(requirements=req_items, design=design, target_url=target_url)

    unified_path = sdir / "unified-model.json"
    save_json(unified_path, unified.model_dump(mode="json"))
    state = SessionState(
        session_id=session_id,
        created_at=now,
        target_url=target_url,
        requirements_files=requirements + requirement_urls,
        figma_file_key=figma_file_key,
        unified_model_path=str(unified_path),
        input_coverage_report_path=str(input_coverage_path) if requirements else None,
    )
    save_session(state)
    return session_id
