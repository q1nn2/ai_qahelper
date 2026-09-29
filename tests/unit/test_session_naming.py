from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

from ai_qahelper.session_naming import build_session_id


def test_build_session_id_format_and_label() -> None:
    fixed = datetime(2026, 4, 13, 12, 0, 0, tzinfo=UTC)
    mock_uuid = MagicMock()
    mock_uuid.hex = "abcdef1234567890"
    with patch("ai_qahelper.session_naming.uuid4", return_value=mock_uuid):
        sid = build_session_id(
            created_at=fixed,
            target_url="https://example.com",
            local_requirement_paths=[],
            session_label="smoke",
        )
    assert sid == "2026-04-13_12-00-00_smoke_abcdef"
    assert "smoke" in sid
