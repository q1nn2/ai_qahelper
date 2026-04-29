"""
Сборка нормализованных файлов в training_data/* из .tmp_training_sources.

Запуск из корня ai_qahelper:
    python tools/normalize_training_packs.py

Не трогает mobile_metro_app. Не подключает training_data к knowledge_base.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TMP = REPO_ROOT / ".tmp_training_sources"
MESTO = TMP / "mesto"
ROUTES = TMP / "routes"
CAR = TMP / "carsharing"
TR = REPO_ROOT / "training_data"

GOOGLE_SHEETS_FAILURE = (
    "Google Sheets не удалось импортировать автоматически. Требуется ручной экспорт в CSV."
)


def _git_show(repo: Path, ref_path: str) -> str:
    raw = subprocess.check_output(
        ["git", "-C", str(repo), "show", ref_path],
    ).decode("utf-8", errors="replace")
    return raw


def _strip_nav(text: str) -> str:
    text = text.lstrip("\ufeff")
    lines = text.splitlines()
    if lines and lines[0].startswith("[←"):
        lines = lines[1:]
    return "\n".join(lines).strip()


def _neutral_sprint_outside_urls(text: str) -> str:
    """Убирает «Sprint» из обычного текста; оставляет внутри http(s) URL."""
    import re as _re

    link = _re.compile(r"https?://\S+")

    def seg(s: str) -> str:
        s = _re.sub(r"\bSprint\s*[_\s]*\d+\b", "учебный модуль", s, flags=_re.IGNORECASE)
        s = _re.sub(r"\bSprint\b", "учебный модуль", s, flags=_re.IGNORECASE)
        s = _re.sub(r"Sprint_\d+_yandex", "yandex", s, flags=_re.IGNORECASE)
        return s

    out: list[str] = []
    pos = 0
    for m in link.finditer(text):
        out.append(seg(text[pos : m.start()]))
        out.append(m.group(0))
        pos = m.end()
    out.append(seg(text[pos:]))
    return "".join(out)


def mesto_test_case_block(raw: str, fn: str) -> str:
    t = _strip_nav(raw)
    t = _neutral_sprint_outside_urls(t)
    m = re.match(r"^#\s+(TK-\d+)\s+—\s+(.+?)\s*$", t.split("\n")[0], re.DOTALL)
    tc_id = m.group(1) if m else fn.replace(".md", "")
    title = m.group(2).strip() if m else ""
    pred = ""
    steps: list[str] = []
    expected = ""
    status = ""
    bug_link = ""
    note = ""

    if "**Предусловие:**" in t or "**Предусловия:**" in t:
        pm = re.search(r"\*\*Предуслови[ея]:\*\*\s*(.+?)(?=\n## |\n\*\*|$)", t, re.DOTALL)
        if pm:
            pred = pm.group(1).strip()

    sh = re.search(r"## Шаги\n(.*?)(?=\n## |\Z)", t, re.DOTALL)
    if sh:
        for line in sh.group(1).strip().splitlines():
            line = line.strip()
            if re.match(r"^\d+\.\s*", line):
                steps.append(re.sub(r"^\d+\.\s*", "", line))

    er = re.search(r"## Ожидаемый результат\n(.*?)(?=\n## |\Z)", t, re.DOTALL)
    if er:
        expected = er.group(1).strip()

    st = re.search(r"## Статус\n(.*?)(?=\n## |\Z)", t, re.DOTALL)
    if st:
        status = st.group(1).strip()

    lk = re.search(r"## Связанн(ый|ые) баг-репорт.*?\n(.*?)(?=\n## |\Z)", t, re.DOTALL)
    if lk:
        bug_link = lk.group(2).strip()

    lines_out = [
        f"### {tc_id}",
        f"- **Название:** {title}",
        f"- **Предусловия:** {pred or '—'}",
        "- **Шаги:**",
    ]
    if steps:
        for i, s in enumerate(steps, 1):
            lines_out.append(f"  {i}. {s}")
    else:
        lines_out.append("  1. —")
    lines_out.extend(
        [
            f"- **Ожидаемый результат:** {expected or '—'}",
            f"- **Статус:** {status or '—'}",
            f"- **ID баг-репорта:** {bug_link or '—'}",
        ]
    )
    if note:
        lines_out.append(f"- **Примечание:** {note}")
    lines_out.append("")
    return "\n".join(lines_out)


def mesto_bug_block(raw: str, fn: str) -> str:
    t = _strip_nav(raw)
    t = _neutral_sprint_outside_urls(t)
    hid = fn.replace(".md", "")
    m = re.match(r"^#\s+(\S+)\s+—\s+(.+)$", t.split("\n")[0])
    bug_id_line = m.group(1) if m else hid
    title = (m.group(2).strip() if m else "")

    pri = ""
    stat = ""
    for line in t.split("\n"):
        if "**Приоритет:**" in line:
            pri = line.split("**Приоритет:**", 1)[-1].strip()
        if line.startswith("**Статус:**"):
            stat = line.split("**Статус:**", 1)[-1].strip()

    pre = ""
    pm = re.search(r"## Предусловия\n(.*?)(?=\n## |\Z)", t, re.DOTALL)
    if pm:
        pre = pm.group(1).strip()

    steps: list[str] = []
    sm = re.search(r"## Шаги воспроизведения\n(.*?)(?=\n## |\Z)", t, re.DOTALL)
    if sm:
        for line in sm.group(1).strip().splitlines():
            line = line.strip()
            if re.match(r"^\d+\.\s*", line):
                steps.append(re.sub(r"^\d+\.\s*", "", line))

    er = re.search(r"## Ожидаемый результат\n(.*?)(?=\n## |\Z)", t, re.DOTALL)
    ar = re.search(r"## Фактический результат\n(.*?)(?=\n## |\Z)", t, re.DOTALL)
    env = ""
    em = re.search(r"## Окружение\n(.*?)(?=\n## |\Z)", t, re.DOTALL)
    if em:
        env = em.group(1).strip()

    comment = ""
    vm = re.search(r"## Вложения\n(.*?)(?=\n## |\Z)", t, re.DOTALL)
    if vm:
        comment = "Вложения: " + vm.group(1).strip()

    lines_out = [
        f"### {bug_id_line} / {hid}",
        f"- **Название:** {title}",
        f"- **Приоритет:** {pri or '—'}",
        f"- **Статус:** {stat or '—'}",
        f"- **Предусловия:** {pre or '—'}",
        "- **Шаги воспроизведения:**",
    ]
    if steps:
        for i, s in enumerate(steps, 1):
            lines_out.append(f"  {i}. {s}")
    else:
        lines_out.append("  1. —")
    lines_out.extend(
        [
            f"- **Ожидаемый результат:** {(er.group(1).strip() if er else '—')}",
            f"- **Фактический результат:** {(ar.group(1).strip() if ar else '—')}",
            f"- **Окружение:** {env or '—'}",
            f"- **Комментарий:** {comment or '—'}",
            "",
        ]
    )
    return "\n".join(lines_out)


def build_web_profile_form() -> None:
    dest = TR / "web_profile_form"
    dest.mkdir(parents=True, exist_ok=True)

    # test cases from branch
    names = (
        subprocess.check_output(
            ["git", "-C", str(MESTO), "ls-tree", "-r", "--name-only", "origin/sprint1-testcases", "testcases"],
        )
        .decode("utf-8", errors="replace")
        .strip()
        .splitlines()
    )
    tc_parts = ["## Test Cases\n"]
    for rel in sorted(names):
        if not rel.endswith(".md"):
            continue
        body = _git_show(MESTO, f"origin/sprint1-testcases:{rel}")
        tc_parts.append(mesto_test_case_block(body, Path(rel).name))

    # bugs
    bnames = (
        subprocess.check_output(
            ["git", "-C", str(MESTO), "ls-tree", "-r", "--name-only", "origin/sprint1-bugreports", "bugreports"],
        )
        .decode("utf-8", errors="replace")
        .strip()
        .splitlines()
    )
    br_parts = ["# Баг-репорты (источник: GitHub Markdown в отдельной ветке; см. `source_links.md`)\n"]
    for rel in sorted(bnames):
        body = _git_show(MESTO, f"origin/sprint1-bugreports:{rel}")
        br_parts.append(mesto_bug_block(body, Path(rel).name))

    (dest / "test_cases.md").write_text("\n".join(tc_parts), encoding="utf-8")
    (dest / "bug_reports.md").write_text("\n".join(br_parts), encoding="utf-8")

    (dest / "requirements.md").write_text(
        _neutral_sprint_outside_urls(
            """# Объект тестирования: Mesto (веб)

- **Краткое описание:** ручное тестирование веб-сервиса Mesto — просмотр и редактирование профиля, работа с карточками; в этом пакете сфокусировано на **форме редактирования профиля** (поля, валидация, сохранение).
- **Тестируемый стенд:** `https://code.s3.yandex.net/qa/files/mesto/index.html`
- **Требования к продукту (Notion):** https://praktikum.notion.site/Mesto-9f2cfaa209734d1f8cfa0c0db3d3049f

## Требования к форме редактирования профиля

- Форма открывается с главной страницы (кнопка с иконкой карандаша).
- Поля формы: **«Имя»** и **«Занятие»** (в требованиях Praktikum к Mesto заданы ограничения по длине и поведению).
- Ограничения длины (по ТЗ): **Имя** — от 2 до 40 символов; **Занятие** — от 2 до 200 символов.
- Кнопка **«Сохранить»** должна сохранять введённые данные и отображать их в блоке профиля на главной странице; при невалидных данных — показывать сообщения об ошибках.
- Закрытие формы без сохранения / с сохранением — по сценариям в тест-кейсах.

## Ссылки на исходные требования

- Notion: https://praktikum.notion.site/Mesto-9f2cfaa209734d1f8cfa0c0db3d3049f
"""
        ),
        encoding="utf-8",
    )

    (dest / "checklist.md").write_text(
        """# Чек-лист

Отдельного файла чек-листа в репозитории нет. Атомарные проверки собраны в виде тест-кейсов **TK-01 … TK-17** в `test_cases.md` (исходные Markdown-файлы в другой ветке того же репозитория GitHub — см. раздел про ветки в `source_links.md`).

Сводные таблицы с теми же кейсами могут быть в Google Sheets (ссылка в `source_links.md`); в этот пакет таблица **не импортировалась автоматически**.
""",
        encoding="utf-8",
    )

    (dest / "learning_notes.md").write_text(
        """# Выводы для обучения агента (web-form testing)

- Это пример **тестирования веб-формы**: профиль, поля, валидация, сохранение.
- Проверять **открытие формы** редактирования с главной страницы.
- Проверять **предзаполнение полей** текущими данными профиля (если предусмотрено сценарием).
- **Валидация «Имя»:** 2–40 символов (граничные и негативные сценарии в TK).
- **Валидация «Занятие»:** 2–200 символов.
- Сценарии с **пустыми значениями** и сообщениями об ошибках.
- Состояние кнопки **«Сохранить»** (активна / неактивна) — в связке с валидностью полей; часть проверок может быть **Blocked**, если форма открывается с дефектом предзаполнения (см. тест-кейсы и ключевые баги в репозитории-источнике).
- **Сохранение данных** на странице после нажатия «Сохранить» и отображение в блоке профиля.
- **Закрытие формы** (с сохранением / без — по кейсам).
- Связь **упавший тест-кейс → баг-репорт** (ID вроде SP1_TK2) — использовать для трассируемости.
- Если предусловие нарушено из-за уже известного бага, связанные тесты могут быть **Blocked** или **Skipped**.

Не использовать статистику конкретного прогона (Passed/Failed) как универсальные правила генерации тестов.
""",
        encoding="utf-8",
    )

    (dest / "test_results_summary.md").write_text(
        """# Сводка результатов прогона (исторический снимок)

Источник: README репозитория-источника (раздел «Итоги»).

## Регрессия

| Метрика       | Значение |
|---------------|----------|
| Всего тестов  | 17       |
| Passed        | 8        |
| Failed        | 7        |
| Blocked       | 2        |

## Ретест (B1–B15)

| Метрика        | Значение |
|----------------|----------|
| Всего дефектов | 15       |
| Closed         | 10       |
| Reopened       | 5        |

## Ключевые дефекты (кратко)

- SP1_TK2 — данные профиля не сохраняются после «Сохранить».
- SP1_TK3 — поле «Занятие» открывается пустым.
- SP1_TK4 — поле «Имя» открывается пустым.

Окружение прогона: Windows 11, Google Chrome 144 (см. README источника).
""",
        encoding="utf-8",
    )

    (dest / "source_links.md").write_text(
        """# Полезные ссылки

## GitHub

- Репозиторий: https://github.com/q1nn2/Sprint_1_yandex_mesto

## Требования и стенд

- Тестируемый стенд: `https://code.s3.yandex.net/qa/files/mesto/index.html`
- Требования (Notion): https://praktikum.notion.site/Mesto-9f2cfaa209734d1f8cfa0c0db3d3049f

## Ветки с артефактами

- Тест-кейсы (Markdown): https://github.com/q1nn2/Sprint_1_yandex_mesto/tree/sprint1-testcases
- Баг-репорты (Markdown): https://github.com/q1nn2/Sprint_1_yandex_mesto/tree/sprint1-bugreports
- Ретест: https://github.com/q1nn2/Sprint_1_yandex_mesto/tree/sprint1-retest

## Google Sheets

- Тест-кейсы: https://docs.google.com/spreadsheets/d/13nzquQs9HWhjU0buZW-GD-v3z_A_sof28SgfXInC4kY/edit?gid=220888493#gid=220888493
- Баг-репорты: https://docs.google.com/spreadsheets/d/1yY5eNi8DMjGEhlcMzAAcT_nKohSqs_---3R_lMUR-n4/edit?gid=1186534874#gid=1186534874
- Ретест: https://docs.google.com/spreadsheets/d/1mqbbYBXJ6YJSuZtBK-uiI9E6lQDbB0JFdRBtRQpQNGg/edit?gid=379530441#gid=379530441

Если нужна сверка с таблицей, экспортируйте лист в CSV вручную при недоступности автоматического экспорта.
""",
        encoding="utf-8",
    )


def routes_bug_md(path: Path) -> str:
    t = path.read_text(encoding="utf-8")
    return _neutral_sprint_outside_urls(t)


def build_web_route_order() -> None:
    dest = TR / "web_route_order"
    dest.mkdir(parents=True, exist_ok=True)

    (dest / "requirements.md").write_text(
        _neutral_sprint_outside_urls(
            """# Объект тестирования: Яндекс Маршруты (веб)

- **Краткое описание:** ручное тестирование веб-сервиса построения маршрутов и расчёта параметров поездки на **собственном автомобиле** (валидация времени и адресов, расчёт стоимости и времени).
- **Тестируемый стенд:** `https://qa-routes.praktikum-services.ru/`
- **Требования к сервису (Google Doc):** https://docs.google.com/document/d/1tIs3KqK79vGR60EoGiDKLavvgsj0cjjrdSRK3AFdY6g/edit

## Основные поля и элементы

- Поля **времени выезда:** «Часы» и «Минуты».
- Поля маршрута: **«Откуда»** и **«Куда»** (адреса).
- Режим и расчёт **стоимости и времени поездки** на своём автомобиле (см. тест-кейсы T60–T65 в `TC-own-car-cost.md`).

## Поведение

- Валидация ввода времени и адресов по ТЗ.
- Построение маршрута и отображение расчётов (стоимость, время) — по сценариям в репозитории.

## Ссылки на требования

- Google Doc: https://docs.google.com/document/d/1tIs3KqK79vGR60EoGiDKLavvgsj0cjjrdSRK3AFdY6g/edit
"""
        ),
        encoding="utf-8",
    )

    # checklist from CE/GZ summaries — structured list
    ce_summary = []
    for name in ("time-fields.md", "address-fields.md", "routes-and-time-intervals.md"):
        p = ROUTES / "ce-gz" / name
        if p.is_file():
            first = p.read_text(encoding="utf-8").split("\n")[0]
            ce_summary.append(f"- **Источник КЭ/ГЗ:** `{name}` — {first.lstrip('# ')}")
    checklist_body = "\n".join(ce_summary) if ce_summary else "- Данные не найдены."
    (dest / "checklist.md").write_text(
        f"""# Checklist

Сводная трассировка к классам эквивалентности и граничным значениям (исходники в `ce-gz/` репозитория).

{checklist_body}

Полный перечень проверок по часам/минутам/адресам и расчёту стоимости см. в `test_cases.md` (агрегация файлов `testcases/*.md`).

Отдельные листы Google Sheets указаны в `source_links.md`. При недоступности экспорта: {GOOGLE_SHEETS_FAILURE}
""",
        encoding="utf-8",
    )

    # test cases: merge all testcase files
    tc_files = sorted((ROUTES / "testcases").glob("*.md"))
    tc_out: list[str] = ["## Test cases (импорт из репозитория)\n"]
    for fp in tc_files:
        intro = f"### Источник файла: `{fp.name}`\n\n"
        tc_out.append(intro)
        for c in routes_parse_md_file(fp):
            tc_out.append(format_routes_tc(c))

    (dest / "test_cases.md").write_text("\n".join(tc_out), encoding="utf-8")

    # bugs — unique files
    bug_dir = ROUTES / "bugreports"
    br: list[str] = ["# Баг-репорты\n"]
    seen: set[str] = set()
    for fp in sorted(bug_dir.glob("BUG*.md")):
        text = routes_bug_md(fp)
        # dedupe by first heading
        h1 = text.split("\n")[0] if text else ""
        if h1 in seen:
            continue
        seen.add(h1)
        br.append(text)
        br.append("\n---\n")

    (dest / "bug_reports.md").write_text("\n".join(br).rstrip() + "\n", encoding="utf-8")

    (dest / "learning_notes.md").write_text(
        """# Выводы для обучения агента (web-flow testing)

- Пример **сквозного сценария** на веб-сервисе: поля времени и адресов, построение маршрута, расчёт стоимости и времени.
- Проверять **поля адресов** «Откуда» и «Куда», обязательность и допустимые значения.
- **Пустые и невалидные значения** в полях времени (часы/минуты).
- Сценарии **построения маршрута** и смены параметров — по тест-кейсам T1–T65.
- **Пересчёт стоимости и времени** поездки на своём авто (группа T60–T65).
- **Состояние кнопок** и сообщения об ошибках при неполных или некорректных данных.
- Связь **чек-листа / КЭ–ГЗ → тест-кейсы → баг-репорты** (ID BUG1–BUG16, привязка в файлах тест-кейсов).

Не использовать KPI конкретного прогона как универсальные правила.
""",
        encoding="utf-8",
    )

    # test results from README tables
    tr = """# Сводка результатов прогона (исторический снимок)

Источник: README репозитория «Яндекс Маршруты» (раздел «Итоги тестирования»).

## Тест-кейсы

| Метрика            | Значение |
|--------------------|----------|
| Всего тест-кейсов  | 64       |
| Passed             | 39       |
| Failed             | 25       |

## Баги

| Метрика     | Значение |
|-------------|----------|
| Всего багов | 16       |
| Критических | 9        |
| Желательных | 7        |

## Ключевые дефекты (по README)

BUG2, BUG3, BUG4, BUG6, BUG7, BUG11, BUG14, BUG15, BUG16 — подробности в отдельных файлах `bugreports/` в источнике.
"""
    (dest / "test_results_summary.md").write_text(tr, encoding="utf-8")

    (dest / "source_links.md").write_text(
        """# Полезные ссылки

## GitHub

- Репозиторий: https://github.com/q1nn2/Sprint_2_yandex_routes

## Стенд и требования

- Стенд: `https://qa-routes.praktikum-services.ru/`
- Требования (Google Doc): https://docs.google.com/document/d/1tIs3KqK79vGR60EoGiDKLavvgsj0cjjrdSRK3AFdY6g/edit

## Google Sheets (общая книга учебного модуля)

- Тест-анализ: https://docs.google.com/spreadsheets/d/1ku3De2DZUbj_QlJKdQU7wEh0N3EIILJ8D6_vwkshmQU/edit?gid=1610041137
- КЭ и ГЗ: https://docs.google.com/spreadsheets/d/1ku3De2DZUbj_QlJKdQU7wEh0N3EIILJ8D6_vwkshmQU/edit?gid=1304990855
- Тест-кейсы: https://docs.google.com/spreadsheets/d/1ku3De2DZUbj_QlJKdQU7wEh0N3EIILJ8D6_vwkshmQU/edit?gid=1524919368
- Баг-репорты: https://docs.google.com/spreadsheets/d/1ku3De2DZUbj_QlJKdQU7wEh0N3EIILJ8D6_vwkshmQU/edit?gid=454479584

Таблицы при необходимости экспортируйте вручную при ошибке автоматического экспорта.
""",
        encoding="utf-8",
    )


def routes_parse_md_file(path: Path) -> list[dict]:
    raw = path.read_text(encoding="utf-8")
    sections = re.split(r"\n---\n", raw)
    cases: list[dict] = []
    for chunk in sections:
        chunk = chunk.strip()
        if not chunk.startswith("## "):
            continue
        first = chunk.split("\n")[0]
        cm = re.match(r"^## (T\d+)\s+—\s+(.+)$", first)
        if not cm:
            continue
        cid = cm.group(1)
        title = cm.group(2).strip()
        pre = ""
        pm = re.search(r"- \*\*Предусловия\*\*:\s*\n(.*?)(?=- \*\*Шаги)", chunk, re.DOTALL)
        if pm:
            pre = re.sub(r"\s+", " ", pm.group(1).strip())
        steps_text = ""
        sm = re.search(r"- \*\*Шаги\*\*:\s*\n(.*?)(?=- \*\*Ожидаемый результат)", chunk, re.DOTALL)
        if sm:
            steps_text = sm.group(1).strip()
        steps_list: list[str] = []
        for line in steps_text.splitlines():
            line = line.strip()
            m = re.match(r"^\d+\.\s*(.+)", line)
            if m:
                steps_list.append(m.group(1))
        exp = ""
        em = re.search(
            r"- \*\*Ожидаемый результат\*\*:\s*\n?\s*(.+?)(?=- \*\*Окружение|\n- \*\*Статус|\Z)",
            chunk,
            re.DOTALL,
        )
        if em:
            exp = re.sub(r"\s+", " ", em.group(1).strip())
        status = ""
        stm = re.search(r"- \*\*Статус\*\*: `([^`]+)`", chunk)
        if stm:
            status = stm.group(1)
        bugs = ""
        bm = re.search(r"- \*\*Связанные баг-репорты\*\*: (.+)", chunk)
        if bm:
            bugs = bm.group(1).strip()
        cases.append(
            {
                "id": cid,
                "title": title,
                "pre": pre,
                "steps": steps_list,
                "expected": exp,
                "status": status,
                "bugs": bugs,
            }
        )
    return cases


def format_routes_tc(c: dict) -> str:
    lines = [
        f"### {c['id']}",
        f"- **Название:** {c['title']}",
        f"- **Предусловия:** {c['pre'] or '—'}",
        "- **Шаги:**",
    ]
    if c["steps"]:
        for i, s in enumerate(c["steps"], 1):
            lines.append(f"  {i}. {s}")
    else:
        lines.append("  1. —")
    lines.extend(
        [
            f"- **Ожидаемый результат:** {c['expected'] or '—'}",
            f"- **Статус:** {c['status'] or '—'}",
            f"- **ID баг-репорта:** {c['bugs'] or '—'}",
            "- **Примечание:** —",
            "",
        ]
    )
    return "\n".join(lines)


def build_carsharing() -> None:
    dest = TR / "web_carsharing_flow"
    dest.mkdir(parents=True, exist_ok=True)

    (dest / "requirements.md").write_text(
        _neutral_sprint_outside_urls(
            """# Объект тестирования: Яндекс Маршруты — каршеринг (веб)

- **Краткое описание:** ручное тестирование сценария **каршеринга** в веб-сервисе: ввод маршрута, выбор режима «Свой» и вида транспорта «Каршеринг», шаги бронирования, оплата и права.
- **Тестируемый стенд:** `https://qa-routes.praktikum-services.ru/`
- **Макеты (Figma):** https://www.figma.com/file/fPw1Xj2dYJy5mdyCg2jduh/%D0%AF%D0%BD%D0%B4%D0%B5%D0%BA%D1%81-%D0%9C%D0%B0%D1%80%D1%88%D1%80%D1%83%D1%82%D1%8B?node-id=2-18586
- **Требования (каршеринг, Yonote):** https://practicum-for-students.yonote.ru/share/0ff0230f-e963-47fa-9a87-8daa1b77fac1/doc/trebovaniya-k-funkcionalnosti-karshering-fF071lXRxM

## Основные шаги заказа (по сценарию тестирования)

1. Задать адреса «Откуда» / «Куда», режим «Свой», вид транспорта «Каршеринг».
2. Перейти к форме бронирования: права, способ оплаты / карта, согласие с условиями — по чек-листам и тест-кейсам.
3. Подтвердить бронирование («Забронировать»); проверить окна состояния заказа и отмены.

## Тарифы и параметры

- Выбор параметров поездки и отображение маршрута/стоимости — в связке с требованиями и макетом.
- Дополнительные поля (права, карта, код) и валидация — см. чек-листы `payment-and-card.md` и баг-репорты.

## Ограничения и валидация

- Детали вложенных форм («Добавление карты», коды и т.д.) — в файлах `checklists/` и `bugreports/` репозитория-источника.
"""
        ),
        encoding="utf-8",
    )

    cl_parts = ["# Checklist\n"]
    for fp in sorted((CAR / "checklists").glob("*.md")):
        cl_parts.append(f"## Файл `{fp.name}`\n\n")
        cl_parts.append(_neutral_sprint_outside_urls(fp.read_text(encoding="utf-8")))
        cl_parts.append("\n\n---\n\n")
    (dest / "checklist.md").write_text("\n".join(cl_parts).rstrip() + "\n", encoding="utf-8")

    # test cases book-button
    book = CAR / "testcases" / "book-button.md"
    tc_text = book.read_text(encoding="utf-8")
    (dest / "test_cases.md").write_text(
        _neutral_sprint_outside_urls(
            "## Test cases\n\n"
            + tc_text.replace("| Шаг |", "| № |").replace("|-----|", "|-----|")
        ),
        encoding="utf-8",
    )

    br: list[str] = ["# Баг-репорты\n"]
    for fp in sorted((CAR / "bugreports").glob("B*.md")):
        br.append(_neutral_sprint_outside_urls(fp.read_text(encoding="utf-8")))
        br.append("\n---\n")
    (dest / "bug_reports.md").write_text("\n".join(br).rstrip() + "\n", encoding="utf-8")

    (dest / "learning_notes.md").write_text(
        """# Выводы для обучения агента (сложный web-flow)

- Пример **многошагового сценария**: маршрут → выбор режима каршеринга → тарифные/пользовательские параметры → бронирование.
- Проверять **переходы между шагами** и **возврат назад** (кнопка «Назад» и соответствие макету).
- Поведение при **отмене** действий и закрытии окон состояния заказа.
- **Сохранение выбранных параметров** при навигации (права, оплата, адреса).
- **Выбор тарифа/режима** и отображение текста на кнопке бронирования.
- **Дополнительные опции** и валидация полей карты/кода.
- **Обязательные условия** для подтверждения заказа.
- **Расчёт стоимости/времени** и тексты маршрута рядом с кнопкой.
- **Подтверждение заказа** и сценарии отмены.
- Связь **требования → тест-кейсы → баг-репорты** (в т.ч. блокирующие дефекты, влияющие на прохождение цепочки).

Не использовать сводные KPI из одного прогона как универсальные правила.
""",
        encoding="utf-8",
    )

    (dest / "test_results_summary.md").write_text(
        """# Сводка результатов прогона (исторический снимок)

Источник: README репозитория каршеринга (раздел «Итоги»).

## Вёрстка (чек-лист Т1–Т60)

| Проверка | Всего | Passed | Failed | Skipped | Blocked |
|----------|------:|-------:|-------:|--------:|--------:|
| Чек-лист вёрстки | 60 | 32 | 18 | 1 | 9 |

## Способ оплаты / карта (Т1–Т38)

| Проверка | Всего | Passed | Failed |
|----------|------:|-------:|-------:|
| Оплата / карта | 38 | 28 | 10 |

## Кнопка «Забронировать»

| Проверка | Всего | Passed | Failed | Skipped | Blocked |
|----------|------:|-------:|-------:|--------:|--------:|
| TC (логика кнопки) | 5 | 1 | 2 | 1 | 1 |

**Блокирующий дефект:** Б19 (окно «Машина забронирована» / отмена) — см. README источника.

Окружение: Windows 11, Chrome 144 (основной), Firefox 800×600 (вёрстка).
""",
        encoding="utf-8",
    )

    (dest / "source_links.md").write_text(
        """# Полезные ссылки

## GitHub

- Репозиторий: https://github.com/q1nn2/Sprint_3_yandex_routes-carsharing-

## Стенд и макеты

- Стенд: `https://qa-routes.praktikum-services.ru/`
- Figma: https://www.figma.com/file/fPw1Xj2dYJy5mdyCg2jduh/%D0%AF%D0%BD%D0%B4%D0%B5%D0%BA%D1%81-%D0%9C%D0%B0%D1%80%D1%88%D1%80%D1%83%D1%82%D1%8B?node-id=2-18586

## Требования

- Каршеринг (Yonote): https://practicum-for-students.yonote.ru/share/0ff0230f-e963-47fa-9a87-8daa1b77fac1/doc/trebovaniya-k-funkcionalnosti-karshering-fF071lXRxM

## Google Sheets

- Сводная таблица: https://docs.google.com/spreadsheets/d/1RUIqS2PpyX0tpLlChrycO3SNLExo3msplwUWW8lf9Qc/edit
- Лист вёрстки (gid=899462569): https://docs.google.com/spreadsheets/d/1RUIqS2PpyX0tpLlChrycO3SNLExo3msplwUWW8lf9Qc/edit?gid=899462569#gid=899462569
- Оплата/карта (gid=1540435533): https://docs.google.com/spreadsheets/d/1RUIqS2PpyX0tpLlChrycO3SNLExo3msplwUWW8lf9Qc/edit?gid=1540435533#gid=1540435533
- Кнопка «Забронировать» (gid=1567345705): https://docs.google.com/spreadsheets/d/1RUIqS2PpyX0tpLlChrycO3SNLExo3msplwUWW8lf9Qc/edit?gid=1567345705#gid=1567345705
- Баг-репорты (gid=977751969): https://docs.google.com/spreadsheets/d/1RUIqS2PpyX0tpLlChrycO3SNLExo3msplwUWW8lf9Qc/edit?gid=977751969#gid=977751969
""",
        encoding="utf-8",
    )


def main() -> None:
    if not MESTO.is_dir():
        print("Нет клона mesto в", MESTO)
        return
    build_web_profile_form()
    if ROUTES.is_dir():
        build_web_route_order()
    if CAR.is_dir():
        build_carsharing()
    print("normalize_training_packs: готово.")


if __name__ == "__main__":
    main()
