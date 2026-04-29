"""
Импорт QA-артефактов из .tmp_training_sources в training_data/.

Не изменяет исходники в .tmp_training_sources/. Запускать из корня ai_qahelper:
    python tools/import_training_data.py
"""

from __future__ import annotations

import csv
import re
import zipfile
from io import StringIO
from pathlib import Path
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET

REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCES_ROOT = REPO_ROOT / ".tmp_training_sources"
TRAINING_ROOT = REPO_ROOT / "training_data"

SOURCE_FOLDER_TO_TRAINING: dict[str, str] = {
    "mesto": "web_profile_form",
    "routes": "web_route_order",
    "carsharing": "web_carsharing_flow",
    "metro_mobile": "mobile_metro_app",
}

METRO_TRAINING = "mobile_metro_app"
METRO_GID_FUNCTIONAL = "899462569"
METRO_GID_REGRESSION = "1540435533"
METRO_GID_BUGS = "165188381"

SKIP_DIR_NAMES = {
    ".git",
    "__pycache__",
    "node_modules",
    ".vscode",
    ".idea",
    "dist",
    "build",
    ".venv",
    "venv",
}

SKIP_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".ico",
    ".svg",
    ".pdf",
    ".zip",
    ".woff",
    ".woff2",
    ".ttf",
    ".eot",
    ".mp4",
    ".webm",
    ".bin",
    ".exe",
    ".dll",
    ".so",
    ".dylib",
}

READ_EXTENSIONS = {".md", ".txt", ".csv"}

_SPREADSHEET_ID_RE = re.compile(r"docs\.google\.com/spreadsheets/d/([a-zA-Z0-9_-]+)")
_GID_PARAM_RE = re.compile(r"[?&#]gid=(\d+)")

URL_PATTERN = re.compile(
    r"(https?://[^\s\]\)\"\'<>]+|"
    r"www\.[^\s\]\)\"\'<>]+)",
    re.IGNORECASE,
)

BUG_HINTS = (
    "баг",
    "баг-репорт",
    "bug report",
    "дефект",
    "фактический результат",
    "actual result",
    "ожидаемый результат",
    "expected result",
    "шаги воспроизведения",
    "steps to reproduce",
)

TEST_HINTS = (
    "тест-кейс",
    "test case",
    "tc-",
    "предусловия",
    "ожидаемый результат",
    "шаг ",
    "шаги",
)

CHECKLIST_HINTS = (
    "чек-лист",
    "checklist",
    "☑",
    "[x]",
    "[ ]",
)

NOISE_H2_PREFIXES = (
    "## Итоги тестирования",
    "## Качество прогона (KPI)",
    "## Качество прогона",
    "## Ключевые достижения",
    "## Список дефектов по приоритетам",
    "## Вывод",
)

_LINK_SEGMENT = re.compile(r"(https?://\S+)")

GOOGLE_SHEETS_FAILURE_NOTE = (
    "Google Sheets не удалось импортировать автоматически. Требуется ручной экспорт в CSV."
)

_SHIELDS_IO_LINE_RE = re.compile(
    r"^\s*!\[[^\]]*\]\(https://img\.shields\.io/[^)]*\)\s*$",
)


def drop_shields_io_lines(text: str) -> str:
    """Удаляет строки с badge-изображениями shields.io из markdown."""
    kept: list[str] = []
    for line in text.splitlines():
        if _SHIELDS_IO_LINE_RE.match(line):
            continue
        kept.append(line)
    return "\n".join(kept)


TRAINING_ARTIFACT_MISSING = (
    "Данные не найдены в доступных источниках. Требуется ручной импорт.\n"
)


def parse_google_sheets_edit_url(url: str) -> tuple[str | None, str | None]:
    """Из ссылки edit вида .../spreadsheets/d/<SHEET_ID>/edit?gid=<GID> извлекает идентификаторы."""
    mid = _SPREADSHEET_ID_RE.search(url)
    gid_m = _GID_PARAM_RE.search(url)
    return (mid.group(1) if mid else None, gid_m.group(1) if gid_m else None)


def spreadsheet_csv_export_url(sheet_id: str, gid: str) -> str:
    return f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid}"


def fetch_csv_export(url: str, *, timeout: int = 45) -> tuple[str | None, str | None]:
    """
    Скачивает CSV по публичному export URL.
    Возвращает (текст CSV, None) или (None, сообщение об ошибке).
    """
    req = Request(url, headers={"User-Agent": "ai_qahelper-training-import/1.0"})
    try:
        with urlopen(req, timeout=timeout) as resp:  # noqa: S310 — только для явных export URL импорта
            raw = resp.read()
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        return None, str(exc)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
    if _is_probably_html(text):
        return None, "Ответ похож на HTML (нет доступа или страница авторизации)."
    body = text.strip()
    if len(body) < 5:
        return None, "Пустой или слишком короткий ответ."
    lines = [ln for ln in body.splitlines() if ln.strip()]
    if len(lines) < 1:
        return None, "Нет строк данных."
    return text, None


def _is_probably_html(text: str) -> bool:
    head = text.lstrip()[:800].lower()
    if head.startswith("<!doctype html") or head.startswith("<html"):
        return True
    if "<meta " in head and "<title>" in head[:1200]:
        return True
    return False


def csv_to_markdown_table(csv_text: str, *, max_rows: int = 600) -> str:
    """Преобразует CSV в markdown-таблицу (pipe)."""
    reader = csv.reader(StringIO(csv_text))
    rows: list[list[str]] = []
    for i, row in enumerate(reader):
        if i >= max_rows:
            break
        rows.append(row)
    if not rows:
        return "(пустой CSV)"
    width = max(len(r) for r in rows)
    norm: list[list[str]] = []
    for r in rows:
        padded = list(r) + [""] * (width - len(r))
        norm.append([c.replace("\n", " ").replace("|", "\\|")[:300] for c in padded[:width]])
    header = norm[0]
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join("---" for _ in header) + " |",
    ]
    for row in norm[1:]:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def _neutralize_sprint_segment(seg: str) -> str:
    """Заменяет учебные упоминания Sprint в тексте вне URL."""
    out = seg
    out = re.sub(r"\bSprint\s*[_\s]*\d+\b", "учебный модуль", out, flags=re.IGNORECASE)
    out = re.sub(r"\bSprint\b", "учебный модуль", out, flags=re.IGNORECASE)
    out = re.sub(r"Sprint_\d+_yandex", "yandex", out, flags=re.IGNORECASE)
    return out


def _neutralize_sprint(text: str) -> str:
    """Заменяет Sprint в тексте; фрагменты http(s)-ссылок не изменяются."""
    chunks: list[str] = []
    pos = 0
    for m in _LINK_SEGMENT.finditer(text):
        chunks.append(_neutralize_sprint_segment(text[pos : m.start()]))
        chunks.append(m.group(0))
        pos = m.end()
    chunks.append(_neutralize_sprint_segment(text[pos:]))
    return "".join(chunks)


def _extract_urls(text: str) -> list[str]:
    found = URL_PATTERN.findall(text)
    seen: set[str] = set()
    result: list[str] = []
    for u in found:
        u = u.rstrip(".,);")
        if u not in seen:
            seen.add(u)
            result.append(u)
    return result


def _extract_spreadsheet_id(text: str) -> str | None:
    m = _SPREADSHEET_ID_RE.search(text)
    return m.group(1) if m else None


def _drop_noise_h2_blocks(text: str) -> str:
    """Удаляет блоки, начинающиеся с перечисленных заголовков ##."""
    blocks = re.split(r"(?=^## )", text, flags=re.MULTILINE)
    out: list[str] = []
    for block in blocks:
        if not block.strip():
            continue
        first_line = block.strip().split("\n", 1)[0].strip()
        drop = any(first_line.startswith(p) for p in NOISE_H2_PREFIXES)
        if first_line.startswith("## Качество прогона"):
            drop = True
        if drop:
            continue
        # строки с KPI отдельно (на случай без заголовка)
        filtered_lines: list[str] = []
        for ln in block.splitlines():
            ll = ln.lower()
            if "pass rate" in ll or "fail rate" in ll:
                continue
            if "blocked rate" in ll or "skipped rate" in ll:
                continue
            filtered_lines.append(ln)
        cleaned = "\n".join(filtered_lines).strip()
        if cleaned:
            out.append(cleaned)
    return "\n\n".join(out).strip()


def _looks_like_bug(text_lower: str) -> bool:
    if "фактический" in text_lower and "ожидаемый" in text_lower:
        return True
    if "actual result" in text_lower and "expected result" in text_lower:
        return True
    return sum(1 for h in BUG_HINTS if h in text_lower) >= 2


def _looks_like_test_cases(text_lower: str, name_lower: str) -> bool:
    if any(h in text_lower for h in TEST_HINTS):
        return True
    if "test" in name_lower and "case" in name_lower:
        return True
    return False


def _looks_like_checklist(text_lower: str) -> bool:
    return any(h in text_lower for h in CHECKLIST_HINTS)


def _read_text_file(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        try:
            return path.read_text(encoding="cp1251")
        except OSError:
            return None


def _read_xlsx_as_text(path: Path) -> tuple[str | None, bool]:
    try:
        with zipfile.ZipFile(path) as zf:
            chunks: list[str] = []
            for name in zf.namelist():
                if not name.endswith(".xml"):
                    continue
                if "sheet" not in name.lower() and "sharedstrings" not in name.lower():
                    continue
                try:
                    data = zf.read(name)
                    root = ET.fromstring(data)
                    for el in root.iter():
                        tag = el.tag.split("}")[-1]
                        if tag == "t" and el.text:
                            chunks.append(el.text)
                except ET.ParseError:
                    continue
        text = "\n".join(chunks).strip()
        return (text if text else None, True)
    except (zipfile.BadZipFile, OSError):
        return (None, False)


def _readme_compact_for_requirements(text: str, *, max_chars: int = 6500) -> str:
    text = drop_shields_io_lines(text)
    neutral = _neutralize_sprint(text)
    stripped = _drop_noise_h2_blocks(neutral)
    out = stripped[:max_chars]
    if len(stripped) > max_chars:
        out += "\n\n[… текст обрезан импортом …]"
    return out.strip()


def _readme_learning_stub(text: str, *, max_chars: int = 2500) -> str:
    text = drop_shields_io_lines(text)
    neutral = _neutralize_sprint(text)
    stripped = _drop_noise_h2_blocks(neutral)
    desc_match = re.search(r"(## Описание\s*\n)([\s\S]*?)(?=\n## |\Z)", stripped)
    if desc_match:
        body = desc_match.group(2).strip()[:max_chars]
        return f"# Выводы для обучения агента\n\nКратко по описанию объекта:\n\n{body}"
    return f"# Выводы для обучения агента\n\n{stripped[:max_chars]}"


METRO_LEARNING_NOTES = """# Выводы для обучения агента (mobile testing example)

- Это пример **мобильного тестирования** клиента метрополитена на Android.
- Нужно проверять **построение маршрута** между станциями и корректность времени в пути и пересадок.
- Проверять **историю станций**: порядок, обновление списка, повторный выбор.
- Проверять **ориентацию экрана** (портрет/альбом) и сохранение состояния карточек и карты.
- Сценарии **отсутствия интернета**, нестабильного канала и **восстановления сети**.
- Поведение при **геолокации** и системных разрешениях.
- Системная кнопка **Back** и возврат по стеку экранов.
- **Сворачивание приложения** и возврат — сохранение построенного маршрута и позиции на схеме.
- **Темы оформления** (светлая/тёмная, автопереключение — если задано в ТЗ).
- Встроенный **WebView** и вызовы внешних приложений (почта, браузер поддержки).

Не использовать статистику конкретного прогона (Passed/Failed) как универсальные правила генерации тестов.
"""


def _metro_requirements_doc(readme_text: str) -> str:
    neutral = _neutralize_sprint(readme_text)
    urls = _extract_urls(neutral)
    ver_m = re.search(r"(?:Метро|приложения)[^\n.]*?(\d+\.\d+)", neutral)
    version = ver_m.group(1) if ver_m else "см. раздел «Окружение» в README"
    plat_m = re.search(r"badge/Platform-([^-\s)]+)", neutral)
    platform = plat_m.group(1).replace("%20", " ") if plat_m else "Android (уточняется по ТЗ)"
    links_md = "\n".join(f"- {u}" for u in urls if "spreadsheets" in u or "notion" in u or "praktikum" in u or "yandex" in u)

    return f"""# Объект тестирования: Яндекс Метро

- **Краткое описание:** ручное тестирование мобильного клиента построения маршрутов и работы со схемой метро.
- **Версия приложения:** {version}
- **Платформа:** {platform}
- **Ссылки на требования и таблицы:**
{links_md or "- (нет извлечённых ссылок)"}

## Основные области тестирования

- Построение и отображение маршрута, время в пути, пересадки.
- История станций и выбор станций отправления/назначения.
- Карта/схема, детали маршрута, состояние UI при смене ориентации.
- Работа без сети и после восстановления соединения.
- Геолокация и разрешения ОС.
- Системная навигация (Back), сворачивание и восстановление приложения.
- Темы оформления и читаемость интерфейса.
- WebView и переходы во внешние приложения.

Источник структуры: README репозитория (статистика прогона intentionally не включена).
"""


def _metro_test_results_summary(readme_text: str) -> str:
    neutral = _neutralize_sprint(readme_text)
    chunks: list[str] = ["# Сводка результатов прогона (исторический снимок)\n"]
    pos_it = neutral.find("## Итоги тестирования")
    pos_def = neutral.find("## Список дефектов по приоритетам")
    if pos_it != -1:
        end = pos_def if pos_def != -1 else len(neutral)
        chunks.append(neutral[pos_it:end].strip())

    pos_kpi = neutral.find("## Качество прогона")
    if pos_kpi != -1 and (pos_def == -1 or pos_kpi < pos_def):
        end_k = pos_def if pos_def != -1 else neutral.find("\n## ", pos_kpi + 5)
        if end_k == -1:
            end_k = neutral.find("\n---\n", pos_kpi)
        if end_k == -1:
            end_k = len(neutral)
        chunks.append(neutral[pos_kpi:end_k].strip())

    pos_out = neutral.find("## Вывод")
    pos_env = neutral.find("## Окружение")
    if pos_out != -1:
        end_o = pos_env if pos_env != -1 else len(neutral)
        chunks.append(neutral[pos_out:end_o].strip())

    return "\n\n---\n\n".join(c for c in chunks if c.strip())


def _append_sheet_failure_note(links_path: Path, *, label: str, gid: str, export_url: str, detail: str | None) -> None:
    block = (
        f"\n\n### SOURCE: Google Sheets ({label}, gid={gid})\n"
        f"- Export URL: `{export_url}`\n"
        f"- {GOOGLE_SHEETS_FAILURE_NOTE}\n"
    )
    if detail:
        block += f"- Детали: {detail}\n"
    existing = links_path.read_text(encoding="utf-8") if links_path.exists() else ""
    links_path.write_text(existing.rstrip() + block, encoding="utf-8")


def _metro_import_google_sheets(sheet_id: str, dest: Path) -> dict[str, bool]:
    """Скачивает CSV для metro и заполняет checklist.md и bug_reports.md."""
    results: dict[str, bool] = {}
    checklist_parts: list[str] = []

    for label, gid in (
        ("Функциональный чек-лист", METRO_GID_FUNCTIONAL),
        ("Регрессионный чек-лист", METRO_GID_REGRESSION),
    ):
        export = spreadsheet_csv_export_url(sheet_id, gid)
        csv_text, err = fetch_csv_export(export)
        results[gid] = csv_text is not None
        if csv_text:
            checklist_parts.append(
                f"### SOURCE: Google Sheets CSV ({label}, gid={gid})\n\n{csv_to_markdown_table(csv_text)}"
            )
        else:
            _append_sheet_failure_note(dest / "source_links.md", label=label, gid=gid, export_url=export, detail=err)

    bug_export = spreadsheet_csv_export_url(sheet_id, METRO_GID_BUGS)
    csv_bugs, err_b = fetch_csv_export(bug_export)
    results[METRO_GID_BUGS] = csv_bugs is not None
    if csv_bugs:
        bug_body = (
            f"### SOURCE: Google Sheets CSV (баг-репорты, gid={METRO_GID_BUGS})\n\n"
            f"{csv_to_markdown_table(csv_bugs)}"
        )
    else:
        _append_sheet_failure_note(
            dest / "source_links.md",
            label="Баг-репорты",
            gid=METRO_GID_BUGS,
            export_url=bug_export,
            detail=err_b,
        )
        bug_body = f"### SOURCE: Google Sheets (gid={METRO_GID_BUGS})\n\n*{GOOGLE_SHEETS_FAILURE_NOTE}*\n"

    (dest / "checklist.md").write_text(
        "\n\n".join(checklist_parts)
        if checklist_parts
        else "_Чек-листы не загружены — см. заметки в `source_links.md`._\n",
        encoding="utf-8",
    )
    (dest / "bug_reports.md").write_text(bug_body, encoding="utf-8")

    return results


def _targets_for_content(
    relative_path: str,
    text: str,
    *,
    is_readme: bool,
) -> list[tuple[str, str]]:
    name_lower = Path(relative_path).name.lower()
    text_lower = text.lower()
    urls = _extract_urls(text)

    results: list[tuple[str, str]] = []

    if urls:
        results.append(("source_links", "\n".join(f"- {u}" for u in urls)))

    if is_readme or name_lower == "readme.md":
        results.append(("requirements", _readme_compact_for_requirements(text)))
        results.append(("learning_notes", _readme_learning_stub(text)))

    elif _looks_like_bug(text_lower):
        results.append(("bug_reports", _neutralize_sprint(text).strip()[:12000]))

    elif _looks_like_checklist(text_lower) and not _looks_like_test_cases(text_lower, name_lower):
        results.append(("checklist", _neutralize_sprint(text).strip()[:12000]))

    elif _looks_like_test_cases(text_lower, name_lower):
        results.append(("test_cases", _neutralize_sprint(text).strip()[:12000]))

    else:
        results.append(("requirements", _readme_compact_for_requirements(text)))

    return results


def _iter_source_files(base: Path) -> Iterable[tuple[str, Path]]:
    for p in base.rglob("*"):
        if p.is_dir():
            continue
        rel = p.relative_to(base)
        parts = rel.parts
        if any(part in SKIP_DIR_NAMES for part in parts):
            continue
        if parts[0] == ".git":
            continue
        suf = p.suffix.lower()
        if suf in SKIP_EXTENSIONS:
            continue
        if suf not in READ_EXTENSIONS and suf != ".xlsx":
            continue
        yield base.name, p


def _append_block(target_file: Path, source_label: str, body: str) -> None:
    block = f"\n\n### SOURCE: {source_label}\n{_neutralize_sprint(body).strip()}\n"
    existing = target_file.read_text(encoding="utf-8") if target_file.exists() else ""
    if existing.strip() in {"", "<!-- Заполняется импортом или вручную -->"}:
        target_file.write_text(block.lstrip(), encoding="utf-8")
    else:
        target_file.write_text(existing.rstrip() + block, encoding="utf-8")


def _ensure_placeholder_removed(path: Path) -> None:
    placeholder = "<!-- Заполняется импортом или вручную -->"
    if path.exists():
        t = path.read_text(encoding="utf-8")
        if t.strip() == placeholder:
            path.write_text("", encoding="utf-8")


def _write_source_repo_links() -> None:
    links = [
        ("web_profile_form", "https://github.com/q1nn2/Sprint_1_yandex_mesto", "mesto"),
        ("web_route_order", "https://github.com/q1nn2/Sprint_2_yandex_routes", "routes"),
        ("web_carsharing_flow", "https://github.com/q1nn2/Sprint_3_yandex_routes-carsharing-", "carsharing"),
        ("mobile_metro_app", "https://github.com/q1nn2/Sprint_4_mobile_Yandex_metro", "metro_mobile"),
    ]
    for folder, url, clone_dir in links:
        p = TRAINING_ROOT / folder / "source_links.md"
        block = (
            f"\n\n### SOURCE: GitHub и локальный клон\n"
            f"- Репозиторий: {url}\n"
            f"- Локальный клон: `.tmp_training_sources/{clone_dir}/`\n"
        )
        existing = p.read_text(encoding="utf-8") if p.exists() else ""
        if url not in existing:
            p.write_text(existing.rstrip() + "\n" + block, encoding="utf-8")


def _import_metro_mobile(base: Path, training_folder: str) -> None:
    dest = TRAINING_ROOT / training_folder
    readme_path = base / "README.md"
    if not readme_path.is_file():
        return
    readme_raw = _read_text_file(readme_path)
    if not readme_raw:
        return

    sheet_id = _extract_spreadsheet_id(readme_raw)

    (dest / "requirements.md").write_text(_metro_requirements_doc(readme_raw), encoding="utf-8")
    (dest / "learning_notes.md").write_text(METRO_LEARNING_NOTES, encoding="utf-8")
    (dest / "test_results_summary.md").write_text(_metro_test_results_summary(readme_raw), encoding="utf-8")

    url_lines = "\n".join(f"- {u}" for u in _extract_urls(readme_raw))
    (dest / "source_links.md").write_text(
        f"# Ссылки (из README)\n\n{url_lines}\n",
        encoding="utf-8",
    )

    # Локальные сводки из репозитория — только в test_results_summary
    extra_summary: list[str] = []
    for rel_check in ("checklists/functional.md", "checklists/regression.md"):
        cp = base / Path(rel_check)
        if cp.is_file():
            text = _read_text_file(cp)
            if text:
                extra_summary.append(f"### SOURCE: `{rel_check}`\n\n{_neutralize_sprint(text)}")
    if extra_summary:
        existing_tr = (dest / "test_results_summary.md").read_text(encoding="utf-8")
        (dest / "test_results_summary.md").write_text(
            existing_tr.rstrip() + "\n\n---\n\n" + "\n\n".join(extra_summary),
            encoding="utf-8",
        )

    (dest / "test_cases.md").write_text(
        "### SOURCE: импорт\n\n"
        "Атомарные проверки см. в экспортированных таблицах в `checklist.md` "
        "(функциональный и регрессионный листы Google Sheets).\n",
        encoding="utf-8",
    )

    if sheet_id:
        _metro_import_google_sheets(sheet_id, dest)
    else:
        note = f"\n\n### SOURCE: metro README\n- Не найден spreadsheet id для Google Sheets.\n- {GOOGLE_SHEETS_FAILURE_NOTE}\n"
        p = dest / "source_links.md"
        p.write_text(p.read_text(encoding="utf-8").rstrip() + note, encoding="utf-8")

    narrative_bug = base / "bugreports" / "README.md"
    if narrative_bug.is_file():
        nb = _read_text_file(narrative_bug)
        if nb:
            stripped = _drop_noise_h2_blocks(_neutralize_sprint(nb))
            bug_path = dest / "bug_reports.md"
            bug_path.write_text(
                bug_path.read_text(encoding="utf-8").rstrip()
                + f"\n\n### SOURCE: bugreports/README.md\n\n{stripped[:20000]}",
                encoding="utf-8",
            )


def _process_non_metro_file(
    clone_dir: str,
    training_folder: str,
    path: Path,
    base: Path,
) -> None:
    rel_inside = path.relative_to(base)
    source_label = f".tmp_training_sources/{clone_dir}/{rel_inside.as_posix()}"
    suf = path.suffix.lower()

    if suf == ".xlsx":
        text, ok = _read_xlsx_as_text(path)
        if not ok or not text:
            note = (
                f"\n\n### SOURCE: {source_label}\n"
                f"- Файл: `{path.name}`\n"
                f"- Требуется ручной экспорт или отдельный импорт (xlsx не разобран только средствами стандартной библиотеки).\n"
            )
            link_file = TRAINING_ROOT / training_folder / "source_links.md"
            existing = link_file.read_text(encoding="utf-8") if link_file.exists() else ""
            link_file.write_text(existing.rstrip() + _neutralize_sprint(note), encoding="utf-8")
            return
        normalized = text
    else:
        raw = _read_text_file(path)
        if raw is None:
            return
        normalized = raw

    if path.name.lower() == "readme.md":
        return

    is_readme = False
    targets = _targets_for_content(rel_inside.as_posix(), normalized, is_readme=is_readme)
    target_map: dict[str, list[str]] = {}
    for key, body in targets:
        target_map.setdefault(key, []).append(body)

    for key, bodies in target_map.items():
        merged = "\n\n---\n\n".join(bodies)
        out_path = TRAINING_ROOT / training_folder / f"{key}.md"
        _append_block(out_path, source_label, merged)


def _process_non_metro_readme(clone_dir: str, training_folder: str, path: Path, base: Path) -> None:
    raw = _read_text_file(path)
    if not raw:
        return
    source_label = f".tmp_training_sources/{clone_dir}/{path.name}"
    targets = _targets_for_content("README.md", raw, is_readme=True)
    target_map: dict[str, list[str]] = {}
    for key, body in targets:
        target_map.setdefault(key, []).append(body)
    for key, bodies in target_map.items():
        merged = "\n\n---\n\n".join(bodies)
        out_path = TRAINING_ROOT / training_folder / f"{key}.md"
        _append_block(out_path, source_label, merged)


def main() -> None:
    if not SOURCES_ROOT.is_dir():
        print(f"Нет каталога {SOURCES_ROOT}. Сначала выполните git clone в .tmp_training_sources/.")
        return

    template_files = (
        "requirements.md",
        "checklist.md",
        "test_cases.md",
        "bug_reports.md",
        "learning_notes.md",
        "source_links.md",
        "test_results_summary.md",
    )

    for training_sub in SOURCE_FOLDER_TO_TRAINING.values():
        sub = TRAINING_ROOT / training_sub
        sub.mkdir(parents=True, exist_ok=True)
        for name in template_files:
            fp = sub / name
            if not fp.exists():
                fp.write_text("<!-- Заполняется импортом или вручную -->\n", encoding="utf-8")

    for training_folder in SOURCE_FOLDER_TO_TRAINING.values():
        for fname in template_files:
            _ensure_placeholder_removed(TRAINING_ROOT / training_folder / fname)

    for clone_dir, training_folder in SOURCE_FOLDER_TO_TRAINING.items():
        base = SOURCES_ROOT / clone_dir
        if not base.is_dir():
            print(f"Пропуск: нет {base}")
            continue

        if training_folder == METRO_TRAINING:
            _import_metro_mobile(base, training_folder)
            continue

        readme_path = base / "README.md"
        if readme_path.is_file():
            _process_non_metro_readme(clone_dir, training_folder, readme_path, base)

        for _, path in _iter_source_files(base):
            if path.name.lower() == "readme.md":
                continue
            _process_non_metro_file(clone_dir, training_folder, path, base)

    _write_source_repo_links()
    print("Импорт завершён.")


if __name__ == "__main__":
    main()
