"""Тесты загрузчика базы знаний и импорта training_data."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


def _load_import_tool():
    root = Path(__file__).resolve().parents[1]
    path = root / "tools" / "import_training_data.py"
    spec = importlib.util.spec_from_file_location("import_training_data", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def import_tool():
    return _load_import_tool()


def test_load_knowledge_base_returns_string(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    from ai_qahelper.knowledge_loader import load_knowledge_base

    assert isinstance(load_knowledge_base(), str)


def test_load_knowledge_base_includes_only_knowledge_base(monkeypatch, tmp_path):
    """training_data отключён и не должен попадать в промпт."""
    monkeypatch.chdir(tmp_path)
    kb = tmp_path / "knowledge_base"
    kb.mkdir()
    (kb / "rules.md").write_text("KB_UNIQUE_MARKER_ALPHA", encoding="utf-8")
    td = tmp_path / "training_data"
    td.mkdir()
    (td / "noise.md").write_text("TD_SECRET_NOISE_MARKER", encoding="utf-8")

    from ai_qahelper.knowledge_loader import load_knowledge_base

    out = load_knowledge_base()
    assert "KB_UNIQUE_MARKER_ALPHA" in out
    assert "TD_SECRET_NOISE_MARKER" not in out


def test_load_knowledge_base_skips_empty_md(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    kb = tmp_path / "knowledge_base"
    kb.mkdir()
    (kb / "empty.md").write_text("   \n\t", encoding="utf-8")

    from ai_qahelper.knowledge_loader import load_knowledge_base

    assert load_knowledge_base() == ""


def test_load_knowledge_base_contains_source_headers(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    kb = tmp_path / "knowledge_base"
    kb.mkdir()
    (kb / "a.md").write_text("content", encoding="utf-8")

    from ai_qahelper.knowledge_loader import load_knowledge_base

    assert "### SOURCE:" in load_knowledge_base()


def test_load_knowledge_base_missing_roots(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    from ai_qahelper.knowledge_loader import load_knowledge_base

    assert load_knowledge_base() == ""


def test_parse_google_sheets_edit_url(import_tool):
    sid, gid = import_tool.parse_google_sheets_edit_url(
        "https://docs.google.com/spreadsheets/d/AbC_12-x/edit?gid=899462569#gid=899462569"
    )
    assert sid == "AbC_12-x"
    assert gid == "899462569"


def test_parse_google_sheets_edit_url_alt_query(import_tool):
    sid, gid = import_tool.parse_google_sheets_edit_url(
        "https://docs.google.com/spreadsheets/d/XYZ789/edit#gid=1540435533"
    )
    assert sid == "XYZ789"
    assert gid == "1540435533"


def test_fetch_csv_export_handles_network_failure(monkeypatch, import_tool):
    def boom(*_a, **_k):
        raise OSError("network unreachable")

    monkeypatch.setattr(import_tool, "urlopen", boom)
    text, err = import_tool.fetch_csv_export(
        "https://docs.google.com/spreadsheets/d/foo/export?format=csv&gid=1"
    )
    assert text is None
    assert err is not None


def test_fetch_csv_export_rejects_html(monkeypatch, import_tool):
    class FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return b"<!DOCTYPE html><html><head></head><body>login</body></html>"

    monkeypatch.setattr(import_tool, "urlopen", lambda *a, **k: FakeResp())
    text, err = import_tool.fetch_csv_export("https://example.invalid/x")
    assert text is None
    assert err is not None


def test_import_neutralizes_sprint(import_tool):
    out = import_tool._neutralize_sprint("Название Sprint 1 и Sprint_2_yandex")
    assert "Sprint" not in out


def test_import_targets_readme_to_requirements(import_tool):
    targets = import_tool._targets_for_content(
        "readme.md",
        "# Заголовок\n\n## Описание\nОписание проекта без ссылок.\n",
        is_readme=True,
    )
    keys = [t[0] for t in targets]
    assert "requirements" in keys
    assert "learning_notes" in keys


def test_append_block_adds_source_marker(import_tool, tmp_path):
    target = tmp_path / "out.md"
    import_tool._append_block(target, ".tmp/foo/readme.md", "Body text")
    text = target.read_text(encoding="utf-8")
    assert "### SOURCE: .tmp/foo/readme.md" in text
    assert "Body text" in text


def test_drop_shields_io_lines_removes_badges(import_tool):
    md = "# H\n![t](https://img.shields.io/badge/a-b-blue)\nsafe"
    out = import_tool.drop_shields_io_lines(md)
    assert "img.shields.io" not in out
    assert "safe" in out


def test_neutralize_sprint_preserves_sprint_in_github_path(import_tool):
    s = import_tool._neutralize_sprint(
        "Стенд описан в https://github.com/q1nn2/Sprint_1_yandex_mesto/blob/main/readme конец.",
    )
    assert "github.com/q1nn2/Sprint_1_yandex_mesto" in s


def test_csv_to_markdown_table_roundtrip(import_tool):
    md = import_tool.csv_to_markdown_table("Кол,a\n1,val")
    assert "Кол" in md and "val" in md
    assert "|" in md


def test_training_artifact_placeholder_text(import_tool):
    assert "ручной импорт" in import_tool.TRAINING_ARTIFACT_MISSING
