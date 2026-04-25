from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path
from typing import Any, Literal

import streamlit as st

from ai_qahelper.orchestrator import (
    agent_run,
    create_bug_drafts_from_failures,
    generate_autotests,
    generate_docs,
    run_autotests,
    run_manual,
    sync_reports,
)

Intent = Literal[
    "agent_run",
    "generate_docs",
    "run_manual",
    "generate_autotests",
    "run_autotests",
    "draft_bugs",
    "sync_reports",
    "help",
]

CONFIRMATION_INTENTS = {"run_autotests", "sync_reports"}


def _init_state() -> None:
    st.session_state.setdefault("messages", [])
    st.session_state.setdefault("last_session_id", "")
    st.session_state.setdefault("last_target_url", "")
    st.session_state.setdefault("last_requirements", [])
    st.session_state.setdefault("pending_action", None)


def _remember(role: str, content: str) -> None:
    st.session_state.messages.append({"role": role, "content": content})


def _extract_urls(text: str) -> list[str]:
    return re.findall(r"https?://\S+", text)


def _extract_target_url(text: str) -> str | None:
    urls = _extract_urls(text)
    for url in urls:
        lowered = url.lower()
        if "figma.com" not in lowered and "docs.google.com/spreadsheets" not in lowered:
            return url.rstrip(").,;!")
    return None


def _extract_requirement_urls(text: str, target_url: str | None) -> list[str]:
    urls = []
    for url in _extract_urls(text):
        clean = url.rstrip(").,;!")
        lowered = clean.lower()
        if clean == target_url:
            continue
        if "docs.google.com/spreadsheets" in lowered:
            continue
        if "figma.com" in lowered:
            continue
        urls.append(clean)
    return urls


def _extract_sheet_urls(text: str) -> list[str]:
    return [url.rstrip(").,;!") for url in _extract_urls(text) if "docs.google.com/spreadsheets" in url.lower()]


def _extract_figma_key(text: str) -> str | None:
    match = re.search(r"figma\.com/(?:file|design)/([^/\s?]+)", text)
    if match:
        return match.group(1)
    match = re.search(r"figma[_\s-]*file[_\s-]*key[:=]\s*([A-Za-z0-9_-]+)", text, flags=re.IGNORECASE)
    return match.group(1) if match else None


def _extract_max_cases(text: str) -> int | None:
    patterns = [
        r"(?:max[-_\s]?cases|максимум|до)\s*(\d+)",
        r"(\d+)\s*(?:тест[-_\s]?кейсов|кейсов|проверок|чек[-_\s]?лист)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return int(match.group(1))
    return None


def _wants_checklist(text: str) -> bool:
    lowered = text.lower()
    return "чек-лист" in lowered or "checklist" in lowered or "чеклист" in lowered


def _wants_bug_drafts(text: str) -> bool:
    lowered = text.lower()
    return any(word in lowered for word in ["баг", "bug", "дефект", "bug-report", "баг-репорт"])


def _classify_intent(text: str) -> Intent:
    lowered = text.lower()
    if any(word in lowered for word in ["выгрузи", "sync", "google sheets", "таблиц"]):
        return "sync_reports"
    if any(word in lowered for word in ["запусти автотест", "run autotest", "pytest", "прогон автотест"]):
        return "run_autotests"
    if any(word in lowered for word in ["сгенерируй автотест", "создай автотест", "generate autotest", "playwright"]):
        return "generate_autotests"
    if any(word in lowered for word in ["черновик баг", "создай баг", "draft bugs", "баг-репорт по пад"]):
        return "draft_bugs"
    if any(word in lowered for word in ["ручной прогон", "manual run", "run manual"]):
        return "run_manual"
    if any(word in lowered for word in ["документац", "тест-кейс", "test case", "чек-лист", "checklist", "сгенерируй кейс"]):
        return "generate_docs" if st.session_state.last_session_id else "agent_run"
    if any(word in lowered for word in ["помощь", "что умеешь", "help"]):
        return "help"
    return "agent_run"


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


def _path_link(path: str | None) -> str:
    if not path:
        return "—"
    return f"`{path}`"


def _format_result(payload: dict[str, Any]) -> str:
    summary = payload.get("summary", {}) or {}
    lines = [
        "Готово.",
        f"Session ID: `{payload.get('session_id', '—')}`",
    ]
    if summary:
        summary_items = ", ".join(f"{key}: {value}" for key, value in summary.items())
        lines.append(f"Summary: {summary_items}")
    artifacts = [
        ("Unified model", payload.get("unified_model_path")),
        ("Consistency report", payload.get("consistency_report_path")),
        ("Test analysis", payload.get("test_analysis_path")),
        ("Checklist", payload.get("checklist_path")),
        ("Test cases", payload.get("test_cases_path")),
        ("Bug reports", payload.get("bug_reports_path")),
        ("Manual results", payload.get("manual_results_path")),
        ("Generated tests", payload.get("generated_tests_dir")),
        ("Auto results", payload.get("auto_results_path")),
        ("JUnit report", payload.get("junit_report_path")),
        ("HTML report", payload.get("html_report_path")),
    ]
    visible = [f"- {name}: {_path_link(path)}" for name, path in artifacts if path]
    if visible:
        lines.append("\nАртефакты:\n" + "\n".join(visible))
    return "\n".join(lines)


def _missing_session_message() -> str:
    return (
        "Не вижу активной сессии. Сначала напиши, какие требования взять, "
        "или загрузи файл требований и укажи target URL."
    )


def _execute_action(action: dict[str, Any]) -> str:
    intent: Intent = action["intent"]
    session_id = action.get("session_id") or st.session_state.last_session_id

    if intent == "help":
        return (
            "Я умею работать с проектом обычным текстом:\n"
            "- сгенерировать тест-кейсы или чек-лист по требованиям;\n"
            "- создать Playwright/pytest шаблоны;\n"
            "- запустить автотесты;\n"
            "- создать баг-репорты по падениям;\n"
            "- подготовить ручной прогон;\n"
            "- выгрузить отчёты в Google Sheets.\n\n"
            "Пример: `Возьми requirements.md, target https://example.com и сделай 10 тест-кейсов`."
        )

    if intent == "agent_run":
        payload = agent_run(
            action.get("requirements", []),
            action.get("requirement_urls", []),
            action.get("figma_file_key"),
            target_url=action.get("target_url"),
            max_cases=action.get("max_cases"),
            with_bug_drafts=action.get("with_bug_drafts", False),
            skip_test_analysis=action.get("skip_test_analysis"),
            session_label=action.get("session_label"),
            artifact_type=action.get("artifact_type", "testcases"),
        )
        st.session_state.last_session_id = payload["session_id"]
        st.session_state.last_target_url = action.get("target_url") or st.session_state.last_target_url
        st.session_state.last_requirements = action.get("requirements", [])
        return _format_result(payload)

    if not session_id:
        return _missing_session_message()

    if intent == "generate_docs":
        state = generate_docs(
            session_id,
            max_cases=action.get("max_cases"),
            generate_bug_templates=True if action.get("with_bug_drafts") else None,
            skip_test_analysis=action.get("skip_test_analysis"),
            artifact_type=action.get("artifact_type", "testcases"),
        )
        return _format_result(state.__dict__)

    if intent == "run_manual":
        state = run_manual(session_id)
        return _format_result(state.__dict__)

    if intent == "generate_autotests":
        state = generate_autotests(session_id)
        return _format_result(state.__dict__)

    if intent == "run_autotests":
        state = run_autotests(session_id)
        return _format_result(state.__dict__)

    if intent == "draft_bugs":
        state = create_bug_drafts_from_failures(session_id)
        return _format_result(state.__dict__)

    if intent == "sync_reports":
        test_cases_sheet_url, bug_reports_sheet_url = action.get("sheet_urls", [None, None])[:2]
        if not test_cases_sheet_url or not bug_reports_sheet_url:
            return "Нужно две ссылки Google Sheets: первая для тест-кейсов, вторая для баг-репортов."
        payload = sync_reports(session_id, test_cases_sheet_url, bug_reports_sheet_url)
        return "Готово, синхронизация выполнена.\n\n```json\n" + json.dumps(payload, ensure_ascii=False, indent=2) + "\n```"

    return "Не понял действие. Напиши проще: `сделай тест-кейсы`, `запусти автотесты`, `создай баги`."


def _build_action(text: str, uploaded_paths: list[str]) -> dict[str, Any]:
    target_url = _extract_target_url(text) or st.session_state.last_target_url or None
    intent = _classify_intent(text)
    artifact_type = "checklist" if _wants_checklist(text) else "testcases"
    requirement_urls = _extract_requirement_urls(text, target_url)
    requirements = uploaded_paths or st.session_state.last_requirements

    if intent == "agent_run" and not requirements and not requirement_urls:
        # Allow a free-text requirement by storing it as a temporary markdown file.
        temp_dir = Path(tempfile.gettempdir()) / "ai_qahelper_chat_requirements"
        temp_dir.mkdir(parents=True, exist_ok=True)
        temp_file = temp_dir / "chat-requirement.md"
        temp_file.write_text(text, encoding="utf-8")
        requirements = [str(temp_file)]

    return {
        "intent": intent,
        "session_id": st.session_state.last_session_id,
        "requirements": requirements,
        "requirement_urls": requirement_urls,
        "figma_file_key": _extract_figma_key(text),
        "target_url": target_url,
        "max_cases": _extract_max_cases(text),
        "with_bug_drafts": _wants_bug_drafts(text),
        "skip_test_analysis": None,
        "artifact_type": artifact_type,
        "sheet_urls": _extract_sheet_urls(text),
    }


def _render_sidebar() -> list[str]:
    st.sidebar.header("Контекст")
    st.sidebar.caption("Файлы требований, .md/.txt/.pdf")
    uploaded_files = st.sidebar.file_uploader(
        "Загрузить требования",
        type=["md", "txt", "pdf"],
        accept_multiple_files=True,
        label_visibility="collapsed",
    )
    target_url = st.sidebar.text_input("Target URL", value=st.session_state.last_target_url)
    if target_url:
        st.session_state.last_target_url = target_url
    if st.sidebar.button("Очистить историю"):
        for key in ["messages", "last_session_id", "last_target_url", "last_requirements", "pending_action"]:
            st.session_state.pop(key, None)
        st.rerun()
    if st.session_state.last_session_id:
        st.sidebar.success(f"Активная сессия: {st.session_state.last_session_id}")
    return _save_uploaded_files(uploaded_files)


def main() -> None:
    st.set_page_config(page_title="AI QAHelper Chat", page_icon="🧪", layout="wide")
    _init_state()

    uploaded_paths = _render_sidebar()

    st.title("AI QAHelper Chat")
    st.caption("Пиши обычным языком. Агент сам выберет действие и использует существующий QA pipeline.")

    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    if pending := st.session_state.pending_action:
        with st.chat_message("assistant"):
            st.warning("Это действие изменит внешние отчёты или запустит автотесты. Подтверди запуск.")
            col1, col2 = st.columns(2)
            if col1.button("Да, выполнить", type="primary"):
                with st.spinner("Выполняю..."):
                    answer = _execute_action(pending)
                _remember("assistant", answer)
                st.session_state.pending_action = None
                st.rerun()
            if col2.button("Отмена"):
                st.session_state.pending_action = None
                _remember("assistant", "Ок, действие отменено.")
                st.rerun()

    prompt = st.chat_input("Напиши задачу: сделай тест-кейсы, запусти автотесты, создай баги...")
    if not prompt:
        return

    _remember("user", prompt)
    action = _build_action(prompt, uploaded_paths)

    with st.chat_message("user"):
        st.markdown(prompt)

    if action["intent"] in CONFIRMATION_INTENTS:
        st.session_state.pending_action = action
        answer = "Подготовил действие. Нужно подтверждение перед запуском."
        _remember("assistant", answer)
        with st.chat_message("assistant"):
            st.markdown(answer)
        return

    with st.chat_message("assistant"):
        with st.spinner("Выполняю..."):
            try:
                answer = _execute_action(action)
            except Exception as exc:  # noqa: BLE001 - show user-friendly chat error
                answer = f"Не получилось выполнить действие: `{exc}`"
        st.markdown(answer)
    _remember("assistant", answer)


if __name__ == "__main__":
    main()
