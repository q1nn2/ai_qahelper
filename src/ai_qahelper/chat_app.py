from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

import streamlit as st

from ai_qahelper.chat_agent import ChatContext, ChatResponse, handle_message
from ai_qahelper.chat_planner import ChatPlan


def _init_state() -> None:
    st.session_state.setdefault("messages", [])
    st.session_state.setdefault("last_session_id", "")
    st.session_state.setdefault("last_target_url", "")
    st.session_state.setdefault("last_requirements", [])
    st.session_state.setdefault("last_figma_file_key", "")
    st.session_state.setdefault("test_cases_sheet_url", "")
    st.session_state.setdefault("bug_reports_sheet_url", "")
    st.session_state.setdefault("pending_plan", None)
    st.session_state.setdefault("pending_message", "")


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
    figma_file_key = st.sidebar.text_input("Figma file key", value=st.session_state.last_figma_file_key)
    st.session_state.last_figma_file_key = figma_file_key
    session_id = st.sidebar.text_input("Session ID", value=st.session_state.last_session_id)
    st.session_state.last_session_id = session_id
    output = st.sidebar.selectbox("output", ["testcases", "checklist"], index=0)
    st.session_state.output = output
    max_cases = st.sidebar.number_input("max_cases", min_value=1, max_value=200, value=30)
    st.session_state.max_cases = int(max_cases)
    st.session_state.with_bug_drafts = st.sidebar.checkbox("with_bug_drafts", value=False)
    st.session_state.skip_test_analysis = st.sidebar.checkbox("skip_test_analysis", value=False)
    st.session_state.test_cases_sheet_url = st.sidebar.text_input(
        "Google Sheets URL для тест-кейсов",
        value=st.session_state.test_cases_sheet_url,
    )
    st.session_state.bug_reports_sheet_url = st.sidebar.text_input(
        "Google Sheets URL для баг-репортов",
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
        ]:
            st.session_state.pop(key, None)
        st.rerun()
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
    )


def _sync_context(context: ChatContext) -> None:
    st.session_state.last_session_id = context.session_id or ""
    st.session_state.last_target_url = context.target_url or ""
    st.session_state.last_requirements = context.requirements


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


def main() -> None:
    st.set_page_config(page_title="AI QAHelper Chat", page_icon="🧪", layout="wide")
    _init_state()

    uploaded_paths = _render_sidebar()

    st.title("AI QAHelper Chat")
    st.caption("Пиши обычным языком. Агент построит план и выполнит QA pipeline по шагам.")

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

    prompt = st.chat_input("Напиши задачу: сделай тест-кейсы, запусти автотесты, создай баги...")
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
                response = ChatResponse(f"Не получилось выполнить действие: `{exc}`")
        if response.plan:
            _render_plan(response.plan)
        st.markdown(response.message)
        _render_step_results(response)
    if response.needs_confirmation and response.plan:
        st.session_state.pending_plan = response.plan.model_dump(mode="json")
        st.session_state.pending_message = prompt
    else:
        _sync_context(context)
    _remember("assistant", response.message)


if __name__ == "__main__":
    main()
