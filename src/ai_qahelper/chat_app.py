from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any, Callable, MutableMapping

import pandas as pd
import streamlit as st

from ai_qahelper.chat_agent import (
    AgentMemory,
    ChatContext,
    ChatResponse,
    handle_message,
    load_agent_memory,
)
from ai_qahelper.chat_planner import ChatPlan
from ai_qahelper.config import (
    get_openai_api_key,
    is_placeholder_api_key,
    load_project_env,
    save_openai_api_key_to_env,
    set_runtime_openai_api_key,
)
from ai_qahelper.friendly_errors import format_technical_error, format_user_error
from ai_qahelper.template_service import (
    DocumentationTemplate,
    default_template,
    enabled_columns,
    load_active_template,
    reset_user_template,
    save_session_template,
    save_user_template,
)
from ai_qahelper.ui_documents import (
    approve_bug_reports_final,
    approve_checklist_final,
    approve_test_cases_final,
    build_local_quality_status,
    create_final_files_zip,
    create_session_zip,
    export_final_bug_reports_xlsx,
    export_final_checklist_xlsx,
    export_final_test_cases_xlsx,
    find_session_artifacts,
    list_export_files,
    load_bug_reports_for_ui,
    load_checklist_for_ui,
    load_test_cases_for_ui,
    save_bug_reports_from_ui,
    save_checklist_from_ui,
    save_test_cases_from_ui,
)

SUPPORTED_UPLOAD_TYPES = ["md", "txt", "pdf", "docx", "xlsx", "xls"]
TASK_TYPES = (
    "Test cases",
    "Checklist",
    "Quality check",
    "Risk analysis",
    "Bug reports draft",
    "Autotests draft",
)
TASK_FOCUS_OPTIONS = (
    "General",
    "Smoke",
    "Negative",
    "Regression",
    "Boundary",
    "UI",
    "API",
    "Mobile",
    "Accessibility",
)
MAIN_SCREEN_CAPTION = (
    "Загрузите требования или укажите URL тестируемого стенда, затем сформулируйте QA-задачу: "
    "сгенерировать тест-кейсы, чек-лист, negative/smoke проверки или выполнить первичный анализ сайта."
)
MISSING_API_KEY_MESSAGE = (
    "OPENAI_API_KEY не найден. Вставьте ключ ниже и нажмите “Сохранить”.\n"
    "Ключ можно сохранить только на текущую сессию или записать в локальный .env."
)
MISSING_TASK_API_KEY_WARNING = "Добавьте OPENAI_API_KEY в блоке «Настройка AI», чтобы использовать AI."
MISSING_TASK_CONTEXT_WARNING = (
    "Недостаточно входных данных. Загрузите требования, укажите URL тестируемого стенда "
    "или выберите существующую Session ID."
)
MISSING_QUICK_ACTION_API_KEY_WARNING = MISSING_TASK_API_KEY_WARNING
MISSING_QUICK_ACTION_CONTEXT_WARNING = MISSING_TASK_CONTEXT_WARNING


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
    st.session_state.setdefault("llm_call_requested", False)
    st.session_state.setdefault("tc_only_problematic", False)
    st.session_state.setdefault("checklist_only_problematic", False)
    st.session_state.setdefault("quality_only_problematic", False)


def should_remember_message(messages: list[dict[str, str]], role: str, content: str) -> bool:
    if not messages:
        return True
    for message in reversed(messages):
        if message.get("role") == role:
            return message.get("content") != content
    return True


def _remember_unique(role: str, content: str) -> None:
    if should_remember_message(st.session_state.messages, role, content):
        st.session_state.messages.append({"role": role, "content": content})


def has_generation_context(context: ChatContext) -> bool:
    return bool(context.requirements or context.requirement_urls or context.target_url or context.session_id)


def build_task_prompt(task_type: str, focus: str, max_cases: int | None = None) -> str:
    normalized_focus = (focus or "General").strip()
    focus_prefix = "" if normalized_focus == "General" else f"{normalized_focus.lower()} "

    if task_type == "Test cases":
        return f"Сгенерируй {focus_prefix}test cases по текущему контексту с полным покрытием требований."
    if task_type == "Checklist":
        return f"Сгенерируй {focus_prefix}checklist по текущему контексту с полным покрытием требований."
    if task_type == "Quality check":
        return "Проверь качество текущей тестовой документации."
    if task_type == "Risk analysis":
        return "Найди риски, противоречия и серые зоны в требованиях."
    if task_type == "Bug reports draft":
        return "Создай черновики bug reports по текущей сессии и найденным проблемам."
    if task_type == "Autotests draft":
        return "Подготовь Playwright/pytest автотесты по текущей сессии, но не запускай их."
    raise ValueError(f"Unknown task type: {task_type}")


def validate_task_run(context: ChatContext, *, has_api_key: bool | None = None) -> str | None:
    if has_api_key is None:
        has_api_key = get_openai_api_key() is not None
    if not has_api_key:
        return MISSING_TASK_API_KEY_WARNING
    if not has_generation_context(context):
        return MISSING_TASK_CONTEXT_WARNING
    return None


def validate_quick_action(context: ChatContext, prompt: str, *, has_api_key: bool | None = None) -> str | None:
    if not prompt:
        return None
    return validate_task_run(context, has_api_key=has_api_key)


def remember_warning_once(messages: list[dict[str, str]], warning: str) -> bool:
    if not warning:
        return False
    if not should_remember_message(messages, "assistant", warning):
        return False
    messages.append({"role": "assistant", "content": warning})
    return True


def run_validated_ai_action(
    context: ChatContext,
    prompt: str,
    *,
    has_api_key: bool | None = None,
    ai_runner: Callable[[ChatContext, str], ChatResponse] | None = None,
    messages: list[dict[str, str]] | None = None,
) -> tuple[ChatResponse | None, str | None]:
    warning = validate_quick_action(context, prompt, has_api_key=has_api_key)
    if warning:
        return None, warning
    runner = ai_runner or run_ai_action
    return runner(context, prompt), None


def run_ai_action(
    context: ChatContext,
    prompt: str,
    *,
    confirmed: bool = False,
    plan: ChatPlan | None = None,
) -> ChatResponse:
    """
    Единственная точка входа для действий, которые вызывают LLM.
    Использовать только для кнопок с пометкой 'через AI' или явной отправки сообщения в Generate.
    """

    st.session_state["llm_call_requested"] = True
    return handle_message(context, prompt, confirmed=confirmed, plan=plan, allow_llm=True)


def clear_chat_state(state: MutableMapping[str, Any]) -> None:
    state["messages"] = []
    state["pending_plan"] = None
    state["pending_message"] = ""


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
    st.sidebar.header("Workspace")
    session_id = st.sidebar.text_input("Session ID", value=st.session_state.last_session_id)
    st.session_state.last_session_id = session_id.strip()
    output = st.sidebar.selectbox("Тип результата", ["testcases", "checklist"], index=0)
    st.session_state.output = output
    st.sidebar.info(
        "Агент сам определяет объём документации на основе покрытия требований. "
        "После генерации будет создан coverage report."
    )
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
    if st.session_state.last_session_id and not st.session_state.agent_context:
        st.session_state.agent_context = load_agent_memory(st.session_state.last_session_id).to_dict()
    if st.session_state.last_session_id:
        st.sidebar.success(f"Активная сессия: {st.session_state.last_session_id}")
    return st.session_state.last_requirements


def _render_context_panel() -> list[str]:
    with st.container(border=True):
        st.subheader("Project Setup")
        st.caption("Задайте входной контекст для QA workflow: требования, стенд, Figma или существующую сессию.")
        left, right = st.columns([2, 1])
        with left:
            uploaded_files = st.file_uploader(
                "Requirements files",
                type=SUPPORTED_UPLOAD_TYPES,
                accept_multiple_files=True,
                help="Поддерживаются .md, .txt, .pdf, .docx, .xlsx, .xls",
            )
            uploaded_paths = _save_uploaded_files(uploaded_files)
            if uploaded_paths:
                st.session_state.last_requirements = uploaded_paths
            target_url = st.text_input("Target URL", value=st.session_state.last_target_url)
            st.session_state.last_target_url = target_url.strip()
        with right:
            figma_file_key = st.text_input("Figma file key", value=st.session_state.last_figma_file_key)
            st.session_state.last_figma_file_key = figma_file_key.strip()
            session_id = st.text_input("Continue Session ID", value=st.session_state.last_session_id, key="generate-session-id")
            st.session_state.last_session_id = session_id.strip()
            if st.session_state.last_session_id and not st.session_state.agent_context:
                st.session_state.agent_context = load_agent_memory(st.session_state.last_session_id).to_dict()
        _render_task_readiness(_build_context(st.session_state.last_requirements), has_api_key=get_openai_api_key() is not None)
    return st.session_state.last_requirements


def _build_context(requirements: list[str]) -> ChatContext:
    return ChatContext(
        requirements=requirements,
        figma_file_key=st.session_state.last_figma_file_key or None,
        target_url=st.session_state.last_target_url or None,
        session_id=st.session_state.last_session_id or None,
        max_cases=None,
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


def _render_technical_error(response: ChatResponse) -> None:
    if not response.technical_error:
        return
    with st.expander("Техническая информация"):
        st.code(response.technical_error)


def _render_next_steps(response: ChatResponse) -> None:
    if not response.suggested_next_steps:
        return
    st.subheader("Что можно сделать дальше")
    for step in response.suggested_next_steps:
        st.write(f"- {step}")


def _render_task_launcher(context: ChatContext) -> str | None:
    return _render_workflow_cards(context)


def _render_workflow_cards(context: ChatContext) -> str | None:
    cards = [
        ("Generate test cases", "Test cases", "General", "Полный набор test cases по требованиям и test conditions."),
        ("Generate checklist", "Checklist", "General", "Атомарный checklist для ручной проверки покрытия."),
        ("Negative coverage", "Test cases", "Negative", "Негативные сценарии, ошибки валидации и отказные состояния."),
        ("Smoke coverage", "Test cases", "Smoke", "Критический happy path и базовая доступность функций."),
        ("Coverage report", "Quality check", "General", "Проверить текущую документацию и coverage artifacts."),
        ("Quality review", "Risk analysis", "General", "Найти риски, gaps и слабые места документации."),
    ]
    with st.container(border=True):
        st.subheader("QA Workflow")
        st.caption(
            "Запустите готовый coverage-first сценарий. Агент сам определит нужное количество проверок."
        )
        has_api_key = get_openai_api_key() is not None
        _render_task_readiness(context, has_api_key=has_api_key)
        st.info(
            "Агент сам определяет объём документации на основе покрытия требований. "
            "После генерации будет создан coverage report."
        )
        for row_start in range(0, len(cards), 3):
            cols = st.columns(3)
            for col, (label, task_type, focus, description) in zip(cols, cards[row_start : row_start + 3], strict=False):
                with col:
                    with st.container(border=True):
                        st.markdown(f"**{label}**")
                        st.caption(description)
                        if st.button("Run", key=f"workflow-{label}", type="primary" if row_start == 0 and label == "Generate test cases" else "secondary"):
                            warning = validate_task_run(context, has_api_key=has_api_key)
                            if warning:
                                st.warning(warning)
                                return None
                            return build_task_prompt(task_type, focus)
    return None


def _render_task_readiness(context: ChatContext, *, has_api_key: bool) -> None:
    requirements_ready = bool(context.requirements or context.requirement_urls)
    target_url_ready = bool(context.target_url)
    session_ready = bool(context.session_id)
    status_cols = st.columns(4)
    status_cols[0].write(f"OPENAI_API_KEY: {'найден' if has_api_key else 'не найден'}")
    status_cols[1].write(f"Требования: {'загружены' if requirements_ready else 'не загружены'}")
    status_cols[2].write(f"URL стенда: {'указан' if target_url_ready else 'не указан'}")
    status_cols[3].write(f"Session ID: {'активна' if session_ready else 'не активна'}")
    if has_api_key and (requirements_ready or target_url_ready or session_ready):
        st.success("Готовность: AI настроен, входной контекст доступен.")
    else:
        st.info("Для запуска нужно добавить OPENAI_API_KEY и загрузить требования/указать URL стенда.")


def _render_manual_command_header() -> None:
    cols = st.columns([3, 1])
    cols[0].subheader("Ручная команда")
    cols[0].caption("Используйте чат для произвольных QA-команд вне карточек workflow.")
    if cols[1].button("Очистить чат", key="manual-clear-chat"):
        clear_chat_state(st.session_state)
        st.rerun()


def _render_welcome() -> None:
    st.info(
        "Начните с Project Setup: загрузите требования или укажите URL тестируемого стенда для Site Discovery.",
        icon="💡",
    )
    col1, col2, col3 = st.columns(3)
    with col1:
        st.subheader("Быстрый старт")
        st.write("1. Загрузите requirements в Project Setup.")
        st.write("2. Укажите ссылку на тестируемый сайт.")
        st.write("3. Запустите карточку QA Workflow или напишите ручную команду.")
    with col2:
        st.subheader("Примеры команд")
        st.write("- `Сделай smoke test cases`")
        st.write("- `Теперь negative cases`")
        st.write("- `Создай баг-репорты`")
        st.write("- `Подготовь автотесты, но не запускай`")
    with col3:
        st.subheader("Что умеет агент")
        st.write("- Test cases и checklists")
        st.write("- Coverage report и gaps/risks")
        st.write("- Site Discovery без требований")
        st.write("- Quality review и dedup")
        st.write("- Playwright/pytest starter tests")
    st.caption(
        "Если требований нет — вставьте Target URL и напишите: "
        "`Проанализируй сайт и сделай smoke test cases`."
    )


def _render_setup_warning() -> None:
    st.subheader("Настройка AI")
    if get_openai_api_key():
        st.success("OPENAI_API_KEY найден. AI готов к работе.")
        return

    st.warning(
        MISSING_API_KEY_MESSAGE,
        icon="⚠️",
    )
    api_key = st.text_input("OPENAI_API_KEY", type="password")
    save_to_env = st.checkbox("Сохранить ключ в локальный .env")
    if not st.button("Сохранить ключ"):
        return
    if not api_key.strip():
        st.error("Введите OPENAI_API_KEY.")
        return
    if is_placeholder_api_key(api_key):
        st.error("Введите корректный OPENAI_API_KEY.")
        return

    set_runtime_openai_api_key(api_key)
    st.session_state["OPENAI_API_KEY"] = api_key.strip()
    if save_to_env:
        save_openai_api_key_to_env(api_key)
    st.success("OPENAI_API_KEY сохранён. AI готов к работе.")
    st.rerun()


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
    if "coverage-report" in name:
        return "Скачать coverage report"
    if "exploratory-report" in name:
        return "Скачать exploratory report"
    if path.suffix.lower() == ".json":
        return "Скачать JSON"
    return f"Скачать {name}"


def _active_session_id() -> str:
    return (st.session_state.last_session_id or "").strip()


def _session_required() -> str | None:
    session_id = _active_session_id()
    if not session_id:
        st.info("Создайте новую сессию во вкладке Generate или укажите существующий Session ID.")
        return None
    return session_id


def _coverage_report_path_for_ui(session_id: str) -> Path | None:
    files = list_export_files(session_id)
    for item in files:
        path = Path(item["path"])
        if path.name.startswith("coverage-report") and path.suffix.lower() == ".json":
            return path
    return None


def _load_coverage_report_for_ui(session_id: str) -> dict[str, Any] | None:
    path = _coverage_report_path_for_ui(session_id)
    if path is None or not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _render_empty_state(title: str, message: str, action: str | None = None) -> None:
    with st.container(border=True):
        st.subheader(title)
        st.write(message)
        if action:
            st.caption(action)


def _render_coverage_dashboard(report: dict[str, Any] | None, *, compact: bool = False) -> None:
    if not report:
        _render_empty_state(
            "Coverage report пока не создан",
            "Запустите coverage-first генерацию во вкладке Generate, чтобы увидеть покрытие требований и gaps.",
            "Основной артефакт: runs/<session_id>/coverage-report.json",
        )
        return
    summary = report.get("summary") or {}
    cols = st.columns(4)
    cols[0].metric("Requirements", f"{summary.get('requirements_covered', 0)}/{summary.get('requirements_total', 0)}")
    cols[1].metric("Partial", summary.get("requirements_partial", 0))
    cols[2].metric("Uncovered", summary.get("requirements_uncovered", 0))
    cols[3].metric("Gaps", len(report.get("gaps") or []))
    cols = st.columns(4)
    cols[0].metric("Test conditions", f"{summary.get('test_conditions_covered', 0)}/{summary.get('test_conditions_total', 0)}")
    cols[1].metric("Test cases", summary.get("test_cases_total", 0))
    cols[2].metric("Duplicates removed", summary.get("duplicates_removed", 0))
    cols[3].metric("Coverage status", "Ready" if not summary.get("requirements_uncovered") else "Needs review")
    if compact:
        return
    st.subheader("Requirements Coverage")
    requirements = report.get("requirements") or []
    if requirements:
        st.dataframe(pd.DataFrame(requirements), use_container_width=True)
    st.subheader("Test Conditions")
    conditions = report.get("test_conditions") or []
    if conditions:
        st.dataframe(pd.DataFrame(conditions), use_container_width=True)
    gaps = report.get("gaps") or []
    if gaps:
        st.subheader("Gaps / Risks")
        st.dataframe(pd.DataFrame(gaps), use_container_width=True)


def _render_dashboard_tab() -> None:
    # Do not call LLM from tab render. LLM is allowed only after explicit user action.
    st.subheader("Dashboard")
    readiness = st.columns(4)
    readiness[0].metric("AI key", "готов" if get_openai_api_key() else "не задан")
    readiness[1].metric("Requirements", len(st.session_state.last_requirements))
    readiness[2].metric("Target URL", "указан" if st.session_state.last_target_url else "не указан")
    readiness[3].metric("Session", _active_session_id() or "-")
    session_id = _session_required()
    if not session_id:
        return
    tc_df = build_local_quality_status(
        load_test_cases_for_ui(session_id),
        "test_cases",
        load_active_template("test_cases", session_id),
    )
    checklist_df = build_local_quality_status(
        load_checklist_for_ui(session_id),
        "checklist",
        load_active_template("checklist", session_id),
    )
    combined = pd.concat([tc_df, checklist_df], ignore_index=True)
    missing_fields = int(combined.get("quality_issues", pd.Series(dtype=str)).str.contains("Missing fields", na=False).sum())
    no_requirement = int(combined.get("quality_issues", pd.Series(dtype=str)).str.contains("No requirement link", na=False).sum())
    duplicates = int(combined.get("duplicate_candidate", pd.Series(dtype=bool)).fillna(False).sum())
    needs_review = int(combined.get("quality_status", pd.Series(dtype=str)).eq("Needs review").sum())
    cols = st.columns(5)
    cols[0].metric("Test cases", len(tc_df))
    cols[1].metric("Checklist", len(checklist_df))
    cols[2].metric("Needs review", needs_review)
    cols[3].metric("Missing fields", missing_fields)
    cols[4].metric("Duplicate candidates", duplicates)
    st.metric("No requirement link", no_requirement)
    st.subheader("Coverage")
    _render_coverage_dashboard(_load_coverage_report_for_ui(session_id), compact=True)
    st.subheader("Последние артефакты")
    st.dataframe(pd.DataFrame(list_export_files(session_id)).head(10), use_container_width=True)


def _render_coverage_tab() -> None:
    # Do not call LLM from tab render. LLM is allowed only after explicit user action.
    st.subheader("Coverage")
    session_id = _session_required()
    if not session_id:
        return
    report_path = _coverage_report_path_for_ui(session_id)
    if report_path:
        st.caption(f"Coverage report: `{report_path}`")
    _render_coverage_dashboard(_load_coverage_report_for_ui(session_id))


def _render_generate_tab(uploaded_paths: list[str]) -> None:
    st.subheader("Generate")
    _render_setup_warning()
    uploaded_paths = _render_context_panel()
    if not st.session_state.messages:
        _render_welcome()
    context = _build_context(uploaded_paths)
    task_prompt = _render_task_launcher(context)
    _render_chat_history()
    _render_manual_command_header()
    _render_pending_confirmation(uploaded_paths)
    _handle_generate_prompt(uploaded_paths, task_prompt)


def _render_chat_history() -> None:
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])


def _render_pending_confirmation(uploaded_paths: list[str]) -> None:
    if not (pending := st.session_state.pending_plan):
        return
    pending_plan = ChatPlan.model_validate(pending)
    with st.chat_message("assistant"):
        st.warning("В плане есть действия, которые требуют подтверждения.")
        _render_plan(pending_plan)
        col1, col2 = st.columns(2)
        if col1.button("Выполнить план через AI", type="primary"):
            context = _build_context(uploaded_paths)
            with st.spinner("Выполняю..."):
                response = run_ai_action(context, st.session_state.pending_message, confirmed=True, plan=pending_plan)
            _sync_context(context)
            _remember_unique("assistant", response.message)
            st.session_state.pending_plan = None
            st.session_state.pending_message = ""
            st.rerun()
        if col2.button("Отмена"):
            st.session_state.pending_plan = None
            st.session_state.pending_message = ""
            _remember_unique("assistant", "Ок, действие отменено.")
            st.rerun()


def _handle_generate_prompt(uploaded_paths: list[str], task_prompt: str | None) -> None:
    context = _build_context(uploaded_paths)
    prompt = task_prompt or st.chat_input("Например: сделай negative cases только для авторизации...")
    if not prompt:
        return
    _remember_unique("user", prompt)
    response = None
    with st.chat_message("user"):
        st.markdown(prompt)
    with st.chat_message("assistant"):
        with st.spinner("Выполняю..."):
            try:
                response = response or run_ai_action(context, prompt)
            except Exception as exc:  # noqa: BLE001 - show user-friendly chat error
                response = ChatResponse(format_user_error(exc), technical_error=format_technical_error(exc))
        _render_ai_response(response)
    if response.needs_confirmation and response.plan:
        st.session_state.pending_plan = response.plan.model_dump(mode="json")
        st.session_state.pending_message = prompt
    _sync_context(context)
    _remember_unique("assistant", response.message)


def _render_ai_response(response: ChatResponse) -> None:
    if response.plan:
        _render_plan(response.plan)
    st.markdown(response.message)
    if response.missing_inputs:
        st.warning("Не хватает данных: " + ", ".join(response.missing_inputs))
    _render_next_steps(response)
    _render_artifact_previews(response)
    _render_step_results(response)
    _render_technical_error(response)


def _render_requirements_tab() -> None:
    st.subheader("Requirements")
    if not st.session_state.last_requirements and not st.session_state.last_target_url and not st.session_state.last_figma_file_key:
        _render_empty_state(
            "Контекст ещё не задан",
            "Откройте Generate и заполните Project Setup: загрузите требования, target URL или Figma key.",
        )
        return
    st.write("Requirements files:")
    if st.session_state.last_requirements:
        for path in st.session_state.last_requirements:
            st.write(f"- `{path}`")
    else:
        st.caption("Файлы требований пока не загружены.")
    if st.session_state.last_target_url:
        st.write(f"Target URL: `{st.session_state.last_target_url}`")
    if st.session_state.last_figma_file_key:
        st.write(f"Figma file key: `{st.session_state.last_figma_file_key}`")


def _render_test_cases_tab(uploaded_paths: list[str]) -> None:
    _render_artifact_table_tab(
        title="Test Cases",
        artifact_type="test_cases",
        load_fn=load_test_cases_for_ui,
        save_fn=save_test_cases_from_ui,
        approve_fn=approve_test_cases_final,
        export_fn=export_final_test_cases_xlsx,
        id_column="case_id",
        detail_column="title",
        ai_buttons=[
            ("Улучшить выбранный test case через AI", "Улучши выбранный test case"),
            ("Перегенерировать проблемные test cases через AI", "Перегенерируй проблемные test cases"),
            ("Добавить negative cases через AI", "Добавь negative cases"),
        ],
        uploaded_paths=uploaded_paths,
    )


def _render_checklist_tab(uploaded_paths: list[str]) -> None:
    _render_artifact_table_tab(
        title="Checklist",
        artifact_type="checklist",
        load_fn=load_checklist_for_ui,
        save_fn=save_checklist_from_ui,
        approve_fn=approve_checklist_final,
        export_fn=export_final_checklist_xlsx,
        id_column="item_id",
        detail_column="check",
        ai_buttons=[
            ("Улучшить выбранную проверку через AI", "Улучши выбранную проверку чек-листа"),
            ("Перегенерировать проблемные пункты через AI", "Перегенерируй проблемные пункты чек-листа"),
        ],
        uploaded_paths=uploaded_paths,
    )


def _render_bug_reports_tab(uploaded_paths: list[str]) -> None:
    _render_artifact_table_tab(
        title="Bug Reports",
        artifact_type="bug_reports",
        load_fn=load_bug_reports_for_ui,
        save_fn=save_bug_reports_from_ui,
        approve_fn=approve_bug_reports_final,
        export_fn=export_final_bug_reports_xlsx,
        id_column="bug_id",
        detail_column="title",
        ai_buttons=[
            ("Улучшить выбранный bug report через AI", "Улучши выбранный bug report"),
            ("Перегенерировать проблемные bug reports через AI", "Перегенерируй проблемные bug reports"),
        ],
        uploaded_paths=uploaded_paths,
    )


def _render_artifact_table_tab(
    *,
    title: str,
    artifact_type: str,
    load_fn: Callable[[str], pd.DataFrame],
    save_fn: Callable[[str, pd.DataFrame], dict],
    approve_fn: Callable[[str], Path],
    export_fn: Callable[[str], Path],
    id_column: str,
    detail_column: str,
    ai_buttons: list[tuple[str, str]],
    uploaded_paths: list[str],
) -> None:
    # Do not call LLM from tab render. LLM is allowed only after explicit user action.
    st.subheader(title)
    session_id = _session_required()
    if not session_id:
        return
    template = load_active_template(artifact_type, session_id)
    df = build_local_quality_status(load_fn(session_id), artifact_type, template)
    if df.empty:
        _render_empty_state(
            f"{title} пока не созданы",
            "Запустите подходящую карточку во вкладке Generate, затем вернитесь сюда для review.",
        )
        return
    filtered = _render_table_filters(_visible_template_columns(df, template), artifact_type, title.lower().replace(" ", "-"))
    edited = st.data_editor(filtered, use_container_width=True, num_rows="dynamic", key=f"{artifact_type}-editor")
    selected_id = st.selectbox("Выбранная строка", edited[id_column].astype(str).tolist(), key=f"{artifact_type}-selected")
    selected = edited[edited[id_column].astype(str) == str(selected_id)].head(1)
    if not selected.empty:
        st.json(selected.iloc[0].to_dict())
    col1, col2, col3 = st.columns(3)
    if col1.button("Сохранить правки JSON", key=f"{artifact_type}-save"):
        saved_df = _merge_edited_rows(df, edited, id_column)
        result = save_fn(session_id, saved_df)
        st.success(f"Сохранено: `{result['path']}`")
    if col2.button("Утвердить final JSON", key=f"{artifact_type}-approve"):
        st.success(f"Создан final: `{approve_fn(session_id)}`")
    if col3.button("Экспортировать final XLSX", key=f"{artifact_type}-export"):
        st.success(f"Создан XLSX: `{export_fn(session_id)}`")
    _render_ai_buttons(uploaded_paths, ai_buttons)


def _render_table_filters(df: pd.DataFrame, artifact_type: str, key_prefix: str) -> pd.DataFrame:
    st.caption("Фильтры работают локально и не вызывают AI.")
    search = st.text_input("Поиск", key=f"{key_prefix}-search")
    cols = st.columns(5)
    priority = cols[0].multiselect("priority", sorted(_non_empty_values(df, "priority")), key=f"{key_prefix}-priority")
    status = cols[1].multiselect("status", sorted(_non_empty_values(df, "status")), key=f"{key_prefix}-status")
    quality = cols[2].multiselect("quality_status", sorted(_non_empty_values(df, "quality_status")), key=f"{key_prefix}-quality")
    only_problematic = cols[3].checkbox("only problematic", key=f"{key_prefix}-problematic")
    no_requirement = cols[4].checkbox("no requirement_id", key=f"{key_prefix}-no-req")
    duplicate_only = st.checkbox("duplicate candidates", key=f"{key_prefix}-dupes")
    result = df.copy()
    if search:
        mask = result.astype(str).apply(lambda row: row.str.contains(search, case=False, na=False).any(), axis=1)
        result = result[mask]
    if priority and "priority" in result:
        result = result[result["priority"].isin(priority)]
    if status and "status" in result:
        result = result[result["status"].isin(status)]
    if quality and "quality_status" in result:
        result = result[result["quality_status"].isin(quality)]
    if only_problematic:
        result = result[result.get("quality_status", "") == "Needs review"]
    if no_requirement:
        result = result[result.get("requirement_id", "").astype(str).str.strip().eq("")]
    if duplicate_only:
        result = result[result.get("duplicate_candidate", False).fillna(False)]
    return result


def _render_ai_buttons(uploaded_paths: list[str], buttons: list[tuple[str, str]]) -> None:
    context = _build_context(uploaded_paths)
    for label, prompt in buttons:
        if st.button(label, key=f"ai-{label}"):
            response, warning = run_validated_ai_action(context, prompt, messages=st.session_state.messages)
            if warning:
                st.warning(warning)
                return
            if response:
                _sync_context(context)
                _remember_unique("assistant", response.message)
                st.success("AI-действие выполнено. Ответ добавлен в историю Generate.")


def _render_quality_tab(uploaded_paths: list[str]) -> None:
    # Do not call LLM from tab render. LLM is allowed only after explicit user action.
    st.subheader("Quality")
    session_id = _session_required()
    if not session_id:
        return
    tc_df = build_local_quality_status(
        load_test_cases_for_ui(session_id),
        "test_cases",
        load_active_template("test_cases", session_id),
    )
    checklist_df = build_local_quality_status(
        load_checklist_for_ui(session_id),
        "checklist",
        load_active_template("checklist", session_id),
    )
    bug_df = build_local_quality_status(
        load_bug_reports_for_ui(session_id),
        "bug_reports",
        load_active_template("bug_reports", session_id),
    )
    quality_df = pd.concat(
        [
            tc_df.assign(artifact="test_cases"),
            checklist_df.assign(artifact="checklist"),
            bug_df.assign(artifact="bug_reports"),
        ],
        ignore_index=True,
    )
    if st.button("Пересчитать локальное качество"):
        st.rerun()
    if st.button("Показать только проблемные"):
        st.session_state.quality_only_problematic = not st.session_state.quality_only_problematic
    if st.session_state.quality_only_problematic and "quality_status" in quality_df:
        quality_df = quality_df[quality_df["quality_status"] == "Needs review"]
    st.write("Quality Summary")
    st.dataframe(_quality_summary(quality_df), use_container_width=True)
    st.dataframe(quality_df, use_container_width=True)
    if st.button("Экспортировать локальный quality report"):
        path = Path(find_session_artifacts(session_id)["session_dir"]) / "local-quality-report.json"
        path.write_text(quality_df.to_json(orient="records", force_ascii=False, indent=2), encoding="utf-8")
        st.success(f"Сохранено: `{path}`")
    _render_ai_buttons(
        uploaded_paths,
        [
            ("Глубокий AI-анализ качества", "Выполни глубокий AI-анализ качества текущей документации"),
            ("Найти серые зоны через AI", "Найди серые зоны через AI по текущей документации"),
            ("Предложить улучшения через AI", "Предложи улучшения через AI для текущей документации"),
        ],
    )


def _render_review_tab(uploaded_paths: list[str]) -> None:
    # Do not call LLM from tab render. LLM is allowed only after explicit user action.
    st.subheader("Review")
    session_id = _session_required()
    if not session_id:
        return
    with st.expander("Quality review", expanded=False):
        _render_quality_tab(uploaded_paths)
    with st.expander("Bug reports", expanded=False):
        _render_bug_reports_tab(uploaded_paths)
    original = load_test_cases_for_ui(session_id, prefer_edited=False)
    edited = load_test_cases_for_ui(session_id, prefer_edited=True)
    if edited.empty:
        _render_empty_state(
            "Test cases для review не найдены",
            "Сначала запустите Generate test cases или Smoke/Negative coverage во вкладке Generate.",
        )
        return
    status = st.selectbox("Массово изменить status", ["", "Draft", "Needs review", "Approved"], key="review-status")
    priority = st.selectbox("Массово изменить priority", ["", "low", "medium", "high", "critical"], key="review-priority")
    selected_ids = st.multiselect("Выберите test cases", edited["case_id"].astype(str).tolist())
    if st.button("Применить массовые изменения") and selected_ids:
        updated = edited.copy()
        mask = updated["case_id"].astype(str).isin(selected_ids)
        if status:
            updated.loc[mask, "status"] = status
        if priority:
            updated.loc[mask, "priority"] = priority
        save_test_cases_from_ui(session_id, updated)
        st.success("Изменения сохранены в test-cases.edited.json")
    st.subheader("Diff original vs edited")
    st.dataframe(pd.concat([original.add_prefix("original_"), edited.add_prefix("edited_")], axis=1), use_container_width=True)
    if selected_ids and st.button("Вернуть selected test case к original"):
        restored = _restore_original_rows(original, edited, selected_ids, "case_id")
        save_test_cases_from_ui(session_id, restored)
        st.success("Выбранные test cases восстановлены из original.")
    if st.button("Утвердить final"):
        st.success(f"Создан final: `{approve_test_cases_final(session_id)}`")


def _render_export_tab() -> None:
    # Do not call LLM from tab render. LLM is allowed only after explicit user action.
    st.subheader("Export")
    session_id = _session_required()
    if not session_id:
        return
    files = list_export_files(session_id)
    if not files:
        _render_empty_state(
            "Артефакты пока не созданы",
            "Запустите coverage-first генерацию во вкладке Generate, чтобы здесь появились JSON/CSV/XLSX файлы.",
        )
    else:
        st.dataframe(pd.DataFrame(files), use_container_width=True)
        coverage_path = _coverage_report_path_for_ui(session_id)
        if coverage_path:
            st.success(f"Coverage report готов: `{coverage_path}`")
        for item in files:
            path = Path(item["path"])
            with st.expander(f"{item['type']}: {item['name']}"):
                st.write(f"`{path}`")
                st.download_button(f"Скачать {path.name}", data=path.read_bytes(), file_name=path.name, key=f"export-{path}")
                if path.suffix.lower() in {".json", ".md"}:
                    _render_artifact_preview(path)
        col1, col2, col3 = st.columns(3)
        if col1.button("Скачать final XLSX"):
            paths = []
            if load_test_cases_for_ui(session_id).shape[0]:
                paths.append(export_final_test_cases_xlsx(session_id))
            if load_checklist_for_ui(session_id).shape[0]:
                paths.append(export_final_checklist_xlsx(session_id))
            if load_bug_reports_for_ui(session_id).shape[0]:
                paths.append(export_final_bug_reports_xlsx(session_id))
            st.success("Создано: " + ", ".join(f"`{p}`" for p in paths))
        if col2.button("Скачать все final-файлы ZIP"):
            path = create_final_files_zip(session_id)
            st.download_button("Скачать final ZIP", data=path.read_bytes(), file_name=path.name)
        if col3.button("Скачать всю сессию ZIP"):
            path = create_session_zip(session_id)
            st.download_button("Скачать session ZIP", data=path.read_bytes(), file_name=path.name)
    with st.expander("Settings and templates"):
        _render_settings_tab()


def _render_settings_tab() -> None:
    # Do not call LLM from tab render. LLM is allowed only after explicit user action.
    st.subheader("Settings")
    st.write(f"session_id: `{_active_session_id() or '-'}`")
    st.write(f"target_url: `{st.session_state.last_target_url or '-'}`")
    st.write(f"output type: `{st.session_state.output}`")
    st.write("AI key status:", "задан" if get_openai_api_key() else "не задан")
    _render_templates_settings()
    col1, col2 = st.columns(2)
    if col1.button("Очистить чат", key="settings-clear-chat"):
        clear_chat_state(st.session_state)
        st.rerun()
    if col2.button("Reset UI state", key="settings-reset-ui"):
        for key in ["tc_only_problematic", "checklist_only_problematic", "quality_only_problematic", "llm_call_requested"]:
            st.session_state.pop(key, None)
        st.rerun()


def _render_templates_settings() -> None:
    st.subheader("Templates")
    artifact_label = st.selectbox(
        "Тип документации",
        ["Test Cases", "Checklist", "Bug Reports"],
        key="template-artifact-label",
    )
    artifact_type = {
        "Test Cases": "test_cases",
        "Checklist": "checklist",
        "Bug Reports": "bug_reports",
    }[artifact_label]
    session_id = _active_session_id() or None
    template = load_active_template(artifact_type, session_id)
    st.caption("Обязательные колонки включены всегда и не отключаются.")
    edited_columns = []
    for idx, column in enumerate(template.columns, start=1):
        cols = st.columns([1, 4, 2, 2])
        enabled = cols[0].checkbox(
            "Вкл.",
            value=True if column.required else column.enabled,
            disabled=column.required,
            key=f"template-{artifact_type}-{column.key}-enabled",
        )
        label = cols[1].text_input("Название", value=column.label, key=f"template-{artifact_type}-{column.key}-label")
        order = cols[2].number_input(
            "Порядок",
            min_value=1,
            max_value=100,
            value=idx,
            step=1,
            key=f"template-{artifact_type}-{column.key}-order",
        )
        cols[3].write("required" if column.required else "optional")
        edited_columns.append((int(order), column.model_copy(update={"label": label, "enabled": enabled or column.required})))
    next_template = DocumentationTemplate(
        name=f"Пользовательский шаблон {artifact_label}",
        artifact_type=artifact_type,  # type: ignore[arg-type]
        columns=[column for _, column in sorted(edited_columns, key=lambda item: item[0])],
    )
    col1, col2, col3 = st.columns(3)
    if col1.button("Сохранить шаблон", key=f"save-template-{artifact_type}"):
        path = save_session_template(session_id, next_template) if session_id else save_user_template(next_template)
        st.success(f"Шаблон сохранён: `{path}`")
    if col2.button("Сбросить к базовому", key=f"reset-template-{artifact_type}"):
        path = save_session_template(session_id, default_template(artifact_type)) if session_id else reset_user_template(artifact_type)
        st.success(f"Восстановлен базовый шаблон: `{path}`")
    if col3.button("Сделать шаблоном по умолчанию", key=f"default-template-{artifact_type}"):
        path = save_user_template(next_template)
        st.success(f"Пользовательский шаблон по умолчанию сохранён: `{path}`")


def _quality_summary(df: pd.DataFrame) -> pd.DataFrame:
    issues = df.get("quality_issues", pd.Series(dtype=str)).fillna("")
    rows = []
    for label in [
        "Missing fields",
        "Empty steps",
        "Weak expected result",
        "No requirement link",
        "Duplicate candidate",
        "Too generic title",
    ]:
        rows.append({"check": label, "count": int(issues.str.contains(label, regex=False).sum())})
    rows.append({"check": "Good", "count": int(df.get("quality_status", pd.Series(dtype=str)).eq("Good").sum())})
    return pd.DataFrame(rows)


def _non_empty_values(df: pd.DataFrame, column: str) -> list[str]:
    if column not in df:
        return []
    return [str(value) for value in df[column].dropna().unique().tolist() if str(value).strip()]


def _merge_edited_rows(original: pd.DataFrame, edited: pd.DataFrame, id_column: str) -> pd.DataFrame:
    result = original.copy()
    if id_column not in result or id_column not in edited:
        return edited
    result = result.set_index(id_column, drop=False)
    for _, row in edited.iterrows():
        item_id = row[id_column]
        result.loc[item_id, row.index] = row
    return result.reset_index(drop=True)


def _visible_template_columns(df: pd.DataFrame, template: DocumentationTemplate) -> pd.DataFrame:
    visible = [column.key for column in enabled_columns(template)]
    aliases = {"notes": "note", "module": "area", "attachment": "attachments"}
    columns = []
    for key in visible:
        if key in df.columns:
            columns.append(key)
        elif aliases.get(key) in df.columns:
            columns.append(aliases[key])
    for helper in ["quality_status", "quality_issues", "duplicate_candidate"]:
        if helper in df.columns:
            columns.append(helper)
    return df[list(dict.fromkeys(columns))] if columns else df


def _restore_original_rows(original: pd.DataFrame, edited: pd.DataFrame, selected_ids: list[str], id_column: str) -> pd.DataFrame:
    result = edited.copy().set_index(id_column, drop=False)
    source = original.copy().set_index(id_column, drop=False)
    for item_id in selected_ids:
        if item_id in source.index:
            result.loc[item_id, source.columns] = source.loc[item_id]
    return result.reset_index(drop=True)


def main() -> None:
    st.set_page_config(page_title="AI QAHelper Chat", page_icon="🧪", layout="wide")
    load_project_env()
    _init_state()

    uploaded_paths = _render_sidebar()

    st.title("AI QAHelper — помощник тестировщика")
    st.caption(MAIN_SCREEN_CAPTION)
    tabs = st.tabs(
        [
            "Dashboard",
            "Generate",
            "Coverage",
            "Requirements",
            "Test Cases",
            "Checklist",
            "Review",
            "Export",
        ]
    )
    with tabs[0]:
        _render_dashboard_tab()
    with tabs[1]:
        _render_generate_tab(uploaded_paths)
    with tabs[2]:
        _render_coverage_tab()
    with tabs[3]:
        _render_requirements_tab()
    with tabs[4]:
        _render_test_cases_tab(uploaded_paths)
    with tabs[5]:
        _render_checklist_tab(uploaded_paths)
    with tabs[6]:
        _render_review_tab(uploaded_paths)
    with tabs[7]:
        _render_export_tab()


if __name__ == "__main__":
    main()
