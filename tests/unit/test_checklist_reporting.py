from __future__ import annotations

from pathlib import Path

from ai_qahelper.models import ChecklistItem
from ai_qahelper.reporting import export_checklist_local


def test_export_checklist_local_creates_files(tmp_path: Path) -> None:
    items = [
        ChecklistItem(
            item_id="CL-001",
            area="Логин",
            check="Проверить успешный вход с валидными данными",
            expected_result="Пользователь авторизован",
            priority="high",
            source_refs=["REQ-1", "COND-01"],
        )
    ]
    csv_path, xlsx_path = export_checklist_local(tmp_path, items)
    assert csv_path.is_file()
    assert xlsx_path.is_file()
