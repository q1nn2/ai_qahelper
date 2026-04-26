from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

import streamlit as st

from ai_qahelper.chat_agent import (
    AgentMemory,
    ChatContext,
    ChatResponse,
    handle_message,
    load_agent_memory,
)
from ai_qahelper.chat_planner import ChatPlan
from ai_qahelper.config import load_project_env

SUPPORTED_UPLOAD_TYPES = ["md", "txt", "pdf", "docx", "xlsx", "xls"]


def _init_state() -> None:
    st.session_state.setdefault("messages", [])
    st.session_state.setdefault("last_session_id", "")
    st.session_state.setdefault("last_target_url", "")
    st.session_state.setdefault("last_requirements", [])
    st.session_state.setdefault("last_figma_file_key", "")
    st.session_state.setdefault("test_cases_sheet_url", "")
    st.session_state.setdefault("bug_reports_sheet_url", "")
    st.session_state.setdefault("site_discovery_max_pages", 5)
    st.session_state.setdefault("site_discovery_max_depth", 1)
    st.session_state.setdefault("site_discovery_same_domain_only", True)
    st.session_state.setdefault("site_discovery_timeout_seconds", 20)
    st.session_state.setdefault("site_discovery_use_playwright", True)
    st.session_state.setdefault("site_discovery_create_screenshots", True)
    st.session_state.setdefault("pending_plan", None)
    st.session_state.setdefault("pending_message", "")
    st.session_state.setdefault("agent_context", {})


def _remember(role: str, content: str) -> None:
    st.session_state.messages.append({"role": role, "content": content})


def _save_uploaded_files(uploaded_files: list[Any]) -> list[str]:
    if not uploaded_files:
        return []
    upload_dir = Path(tempfile.gettempdir()) / "ai_qahelper_chat_uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    paths: list[str] = []
    for uploaded_file in uploaded_files:
        safe_name = Path(uploaded_file.name).name
        path = upload_dir / safe_name
        path.write_bytes(uploaded_file.getbuffer())
        paths.append(str(path))
    return paths


def _render_sidebar() -> list[str]:
    st.sidebar.header("Контекст")
    st.sidebar.subheader("Файлы требований")
    st.sidebar.caption(".md, .txt, .pdf, .docx, .xlsx, .xls")
    uploaded_files = st.sidebar.file_uploader(
        "Загрузить требования",
        type=SUPPORTED_UPLOAD_TYPES,
        accept_multiple_files=True,
        label_visibility="collapsed",
    )
    target_url = st.sidebar.text_input("Ссылка на тестируемый сайт", value=st.session_state.last_target_url)
    if target_url:
        st.session_state.last_target_url = target_url
    figma_file_key = st.sidebar.text_input("Figma file key", value=st.session_state.last_figma_file_key)
    st.session_state.last_figma_file_key = figma_file_key
    session_id = st.sidebar.text_input("ID текущей сессии", value=st.session_state.last_session_id)
    st.session_state.last_session_id = session_id
    output = st.sidebar.selectbox("Тип результата", ["testcases", "checklist"], index=0)
    st.session_state.output = output
    max_cases = st.sidebar.number_input("Количество проверок", min_value=1, max_value=200, value=30)
    st.session_state.max_cases = int(max_cases)
    st.sidebar.subheader("Дополнительные настройки")
    st.session_state.with_bug_drafts = st.sidebar.checkbox("Создавать черновики bug reports", value=False)
    st.session_state.skip_test_analysis = st.sidebar.checkbox("Пропустить отдельный test analysis", value=False)
    with st.sidebar.expander("Расширенные настройки Site Discovery"):
        st.session_state.site_discovery_max_pages = int(
            st.number_input(
                "Максимум страниц",
                min_value=1,
                max_value=20,
                value=int(st.session_state.site_discovery_max_pages),
                help="Безопасный лимит страниц для exploratory discovery.",
            )
        )
        st.session_state.site_discovery_max_depth = int(
            st.number_input(
                "Глубина переходов",
                min_value=0,
                max_value=3,
                value=int(st.session_state.site_discovery_max_depth),
            )
        )
        st.session_state.site_discovery_same_domain_only = st.checkbox(
            "Только тот же домен",
            value=st.session_state.site_discovery_same_domain_only,
        )
        st.session_state.site_discovery_timeout_seconds = int(
            st.number_input(
                "Таймаут, секунд",
                min_value=1,
                max_value=60,
                value=int(st.session_state.site_discovery_timeout_seconds),
            )
        )
        st.session_state.site_discovery_use_playwright = st.checkbox(
            "Использовать Playwright",
            value=st.session_state.site_discovery_use_playwright,
        )
        st.session_state.site_discovery_create_screenshots = st.checkbox(
            "Создавать screenshots",
            value=st.session_state.site_discovery_create_screenshots,
        )
    st.sidebar.subheader("Google Sheets export")
    st.session_state.test_cases_sheet_url = st.sidebar.text_input(
        "URL таблицы для тест-кейсов",
        value=st.session_state.test_cases_sheet_url,
    )
    st.session_state.bug_reports_sheet_url = st.sidebar.text_input(
        "URL таблицы для баг-репортов",
        value=st.session_state.bug_reports_sheet_url,
    )
    if st.sidebar.button("Очистить историю"):
        for key in [
            "messages",
            "last_session_id",
            "last_target_url",
            "last_requirements",
            "last_figma_file_key",
            "pending_plan",
            "pending_message",
            "agent_context",
        ]:
            st.session_state.pop(key, None)
        st.rerun()
    if st.session_state.last_session_id and not st.session_state.agent_context:
        st.session_state.agent_context = load_agent_memory(st.session_state.last_session_id).to_dict()
    if st.session_state.last_session_id:
        st.sidebar.success(f"Активная сессия: {st.session_state.last_session_id}")
    uploaded_paths = _save_uploaded_files(uploaded_files)
    if uploaded_paths:
        st.session_state.last_requirements = uploaded_paths
    return uploaded_paths or st.session_state.last_requirements


def _build_context(requirements: list[str]) -> ChatContext:
    return ChatContext(
        requirements=requirements,
        figma_file_key=st.session_state.last_figma_file_key or None,
        target_url=st.session_state.last_target_url or None,
        session_id=st.session_state.last_session_id or None,
        max_cases=st.session_state.max_cases,
        output=st.session_state.output,
        with_bug_drafts=st.session_state.with_bug_drafts,
        skip_test_analysis=st.session_state.skip_test_analysis,
        test_cases_sheet_url=st.session_state.test_cases_sheet_url or None,
        bug_reports_sheet_url=st.session_state.bug_reports_sheet_url or None,
        site_discovery_max_pages=st.session_state.site_discovery_max_pages,
        site_discovery_max_depth=st.session_state.site_discovery_max_depth,
        site_discovery_same_domain_only=st.session_state.site_discovery_same_domain_only,
        site_discovery_timeout_seconds=st.session_state.site_discovery_timeout_seconds,
        site_discovery_use_playwright=st.session_state.site_discovery_use_playwright,
        site_discovery_create_screenshots=st.session_state.site_discovery_create_screenshots,
        agent_memory=AgentMemory.from_dict(st.session_state.agent_context),
    )


def _sync_context(context: ChatContext) -> None:
    st.session_state.last_session_id = context.session_id or ""
    st.session_state.last_target_url = context.target_url or ""
    st.session_state.last_requirements = context.requirements
    st.session_state.last_figma_file_key = context.figma_file_key or ""
    st.session_state.max_cases = context.max_cases or st.session_state.max_cases
    st.session_state.test_cases_sheet_url = context.test_cases_sheet_url or ""
    st.session_state.bug_reports_sheet_url = context.bug_reports_sheet_url or ""
    st.session_state.site_discovery_max_pages = context.site_discovery_max_pages
    st.session_state.site_discovery_max_depth = context.site_discovery_max_depth
    st.session_state.site_discovery_same_domain_only = context.site_discovery_same_domain_only
    st.session_state.site_discovery_timeout_seconds = context.site_discovery_timeout_seconds
    st.session_state.site_discovery_use_playwright = context.site_discovery_use_playwright
    st.session_state.site_discovery_create_screenshots = context.site_discovery_create_screenshots
    st.session_state.agent_context = context.agent_memory.to_dict()


def _render_plan(plan: ChatPlan) -> None:
    if plan.goal:
        st.info(f"Распознанная цель: {plan.goal}")
    if plan.user_friendly_summary:
        st.caption(plan.user_friendly_summary)
    for idx, action in enumerate(plan.actions, start=1):
        confirm = " (требует подтверждения)" if action.requires_confirmation else ""
        st.write(
            f"{idx}. `{action.type}` / `{action.artifact_type}` / `{action.focus}`"
            f"{confirm} — {action.reason}"
        )


def _render_step_results(response: ChatResponse) -> None:
    if not response.results:
        return
    st.subheader("Результаты шагов")
    for idx, result in enumerate(response.results, start=1):
        title = result.get("title") or result.get("action") or f"Шаг {idx}"
        with st.expander(f"{idx}. {title}", expanded=idx == len(response.results)):
            for key, value in result.items():
                if value and (key.endswith("_path") or key.endswith("_dir") or key == "session_id"):
                    st.write(f"**{key}:** `{value}`")


def _render_next_steps(response: ChatResponse) -> None:
    if not response.suggested_next_steps:
        return
    st.subheader("Что можно сделать дальше")
    for step in response.suggested_next_steps:
        st.write(f"- {step}")


def _render_quick_actions() -> str | None:
    actions = [
        ("Сделать тест-кейсы", "Сделай тест-кейсы"),
        ("Сделать чек-лист", "Сделай чек-лист"),
        ("Smoke", "Сделай smoke test cases"),
        ("Negative", "Теперь сделай negative test cases"),
        ("Bug reports", "Создай баг-репорты"),
        ("Autotests", "Подготовь Playwright/pytest автотесты, но не запускай"),
    ]
    columns = st.columns(4)
    for idx, (label, command) in enumerate(actions):
        if columns[idx % 4].button(label):
            return command
    return None


def _render_welcome() -> None:
    st.info(
        "Загрузите требования или вставьте ссылку на сайт, затем напишите задачу обычным языком.",
        icon="💡",
    )
    col1, col2, col3 = st.columns(3)
    with col1:
        st.subheader("Быстрый старт")
        st.write("1. Загрузите requirements в боковой панели.")
        st.write("2. Укажите ссылку на тестируемый сайт.")
        st.write("3. Нажмите быструю кнопку или напишите команду.")
    with col2:
        st.subheader("Примеры команд")
        st.write("- `Сделай smoke test cases`")
        st.write("- `Теперь negative cases`")
        st.write("- `Создай баг-репорты`")
        st.write("- `Подготовь автотесты, но не запускай`")
    with col3:
        st.subheader("Что умеет агент")
        st.write("- Test cases и checklists")
        st.write("- Site Discovery без требований")
        st.write("- Quality reports и dedup")
        st.write("- Playwright/pytest starter tests")
    st.caption(
        "Если требований нет — вставьте Target URL и напишите: "
        "`Проанализируй сайт и сделай smoke test cases`."
    )


def _render_setup_warning() -> None:
    if os.getenv("OPENAI_API_KEY"):
        return
    st.warning(
        "Не найден OPENAI_API_KEY. Добавьте строку `OPENAI_API_KEY=sk-...` в файл `.env` "
        "или запустите `run_chat_windows.bat` / `run_chat.sh`, чтобы launcher спросил ключ автоматически.",
        icon="⚠️",
    )


def _render_artifact_previews(response: ChatResponse) -> None:
    if not response.artifacts:
        return
    st.subheader("Артефакты")
    for artifact in response.artifacts:
        path = Path(artifact)
        with st.expander(path.name, expanded=path.suffix.lower() in {".md", ".json"}):
            st.write(f"Путь: `{path}`")
            if path.is_file():
                st.download_button(
                    _download_label(path),
                    data=path.read_bytes(),
                    file_name=path.name,
                    key=f"download-{artifact}",
                )
                _render_artifact_preview(path)
            else:
                st.caption("Файл пока не найден локально или это директория.")


def _render_artifact_preview(path: Path) -> None:
    suffix = path.suffix.lower()
    if suffix == ".md":
        st.markdown(path.read_text(encoding="utf-8")[:5000])
    elif suffix == ".json":
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            st.caption("JSON preview недоступен: файл не удалось разобрать.")
            return
        if isinstance(data, list):
            st.write(f"JSON: {len(data)} элементов")
            st.json(data[:3])
        elif isinstance(data, dict):
            st.write(f"JSON keys: {', '.join(list(data.keys())[:10])}")
            summary = data.get("summary") if isinstance(data.get("summary"), dict) else data
            st.json(summary)
    elif suffix in {".csv", ".xlsx", ".xls"}:
        st.caption("Preview для Excel/CSV не открывается в UI, файл можно скачать кнопкой выше.")


def _download_label(path: Path) -> str:
    name = path.name
    if name.endswith(".xlsx") and "test-cases" in name:
        return "Скачать test-cases.xlsx"
    if name.endswith(".xlsx") and "checklist" in name:
        return "Скачать checklist.xlsx"
    if "quality-report" in name:
        return "Скачать quality report"
    if "exploratory-report" in name:
        return "Скачать exploratory report"
    if path.suffix.lower() == ".json":
        return "Скачать JSON"
    return f"Скачать {name}"


def main() -> None:
    st.set_page_config(page_title="AI QAHelper Chat", page_icon="🧪", layout="wide")
    load_project_env()
    _init_state()

    uploaded_paths = _render_sidebar()

    st.title("AI QAHelper — помощник тестировщика")
    st.caption("Загрузите требования или вставьте ссылку на сайт, затем напишите задачу обычным языком.")
    _render_setup_warning()
    if not st.session_state.messages:
        _render_welcome()
    st.subheader("Быстрые действия")
    quick_prompt = _render_quick_actions()

    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    if pending := st.session_state.pending_plan:
        pending_plan = ChatPlan.model_validate(pending)
        with st.chat_message("assistant"):
            st.warning("В плане есть действия, которые требуют подтверждения.")
            _render_plan(pending_plan)
            col1, col2 = st.columns(2)
            if col1.button("Выполнить план", type="primary"):
                context = _build_context(uploaded_paths)
                with st.spinner("Выполняю..."):
                    response = handle_message(
                        context,
                        st.session_state.pending_message,
                        confirmed=True,
                        plan=pending_plan,
                    )
                _sync_context(context)
                _remember("assistant", response.message)
                st.session_state.pending_plan = None
                st.session_state.pending_message = ""
                st.rerun()
            if col2.button("Отмена"):
                st.session_state.pending_plan = None
                st.session_state.pending_message = ""
                _remember("assistant", "Ок, действие отменено.")
                st.rerun()

    prompt = quick_prompt or st.chat_input("Напиши задачу: сделай тест-кейсы, запусти автотесты, создай баги...")
    if not prompt:
        return

    _remember("user", prompt)
    context = _build_context(uploaded_paths)

    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("Выполняю..."):
            try:
                response = handle_message(context, prompt)
            except Exception as exc:  # noqa: BLE001 - show user-friendly chat error
                response = ChatResponse(
                    "Не удалось выполнить действие.\n\n"
                    f"Что случилось: {exc}\n\n"
                    "Что сделать: проверьте входные данные и попробуйте ещё раз."
                )
        if response.plan:
            _render_plan(response.plan)
        st.markdown(response.message)
        if response.missing_inputs:
            st.warning("Не хватает данных: " + ", ".join(response.missing_inputs))
        _render_next_steps(response)
        _render_artifact_previews(response)
        _render_step_results(response)
    if response.needs_confirmation and response.plan:
        st.session_state.pending_plan = response.plan.model_dump(mode="json")
        st.session_state.pending_message = prompt
    _sync_context(context)
    _remember("assistant", response.message)


if __name__ == "__main__":
    main()
