from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Annotated

import typer
from rich import print

from ai_qahelper.orchestrator import (
    agent_run,
    create_bug_drafts_from_failures,
    generate_autotests,
    generate_docs,
    ingest,
    run_autotests,
    run_manual,
    sync_reports,
)

app = typer.Typer(help="Local AI QA helper")


def run_cli() -> None:
    app()


@app.command("chat")
def chat_cmd() -> None:
    """Open AI QAHelper Chat in a local browser window."""

    chat_app_path = Path(__file__).with_name("chat_app.py")
    subprocess.run([sys.executable, "-m", "streamlit", "run", str(chat_app_path)], check=False)


@app.command("ingest")
def ingest_cmd(
    requirements: Annotated[
        list[str],
        typer.Option(
            "--requirement",
            "--requirements",
            "-r",
            help="Local requirement paths (.txt/.md/.pdf); repeat flag for multiple files",
        ),
    ] = [],
    requirement_url: Annotated[list[str], typer.Option(help="Requirement URL")] = [],
    figma_file_key: Annotated[str | None, typer.Option(help="Figma file key")] = None,
    target_url: Annotated[str, typer.Option(help="Target web app URL")] = ...,
    session_label: Annotated[
        str | None,
        typer.Option(
            "--session-label",
            "-L",
            help="Короткая метка для имени папки сессии (иначе — из файла требований или host URL)",
        ),
    ] = None,
) -> None:
    session_id = ingest(requirements, requirement_url, figma_file_key, target_url, session_label=session_label)
    print({"session_id": session_id})


@app.command("generate-docs")
def generate_docs_cmd(
    session_id: str,
    max_cases: Annotated[
        int | None,
        typer.Option(help="Number of checklist items or test cases to generate; overrides config defaults"),
    ] = None,
    with_bug_drafts: Annotated[
        bool,
        typer.Option("--with-bug-drafts", help="Дополнительно сгенерировать черновики баг-репортов (LLM)."),
    ] = False,
    skip_test_analysis: Annotated[
        bool,
        typer.Option("--skip-test-analysis", help="Пропустить LLM шаг тест-анализа (один запрос вместо двух)."),
    ] = False,
    output: Annotated[
        str,
        typer.Option("--output", help="Какой артефакт сгенерировать: testcases или checklist."),
    ] = "testcases",
) -> None:
    bug_arg = True if with_bug_drafts else None
    skip_a = True if skip_test_analysis else None
    state = generate_docs(
        session_id,
        max_cases=max_cases,
        generate_bug_templates=bug_arg,
        skip_test_analysis=skip_a,
        artifact_type="checklist" if output == "checklist" else "testcases",
    )
    print(
        {
            "session_id": state.session_id,
            "test_analysis_path": state.test_analysis_path,
            "checklist_path": state.checklist_path,
            "test_cases_path": state.test_cases_path,
            "bug_reports_path": state.bug_reports_path,
            "artifact_type": output,
        }
    )


@app.command("run-manual")
def run_manual_cmd(session_id: str) -> None:
    state = run_manual(session_id)
    print({"session_id": state.session_id, "manual_results_path": state.manual_results_path})


@app.command("generate-autotests")
def generate_autotests_cmd(session_id: str) -> None:
    state = generate_autotests(session_id)
    print({"session_id": state.session_id, "generated_tests_dir": state.generated_tests_dir})


@app.command("run-autotests")
def run_autotests_cmd(session_id: str) -> None:
    state = run_autotests(session_id)
    print(
        {
            "session_id": state.session_id,
            "auto_results_path": state.auto_results_path,
            "junit_report_path": state.junit_report_path,
            "html_report_path": state.html_report_path,
        }
    )


@app.command("draft-bugs")
def draft_bugs_cmd(session_id: str) -> None:
    state = create_bug_drafts_from_failures(session_id)
    print({"session_id": state.session_id, "bug_reports_path": state.bug_reports_path})


@app.command("sync-reports")
def sync_reports_cmd(session_id: str, test_cases_sheet_url: str, bug_reports_sheet_url: str) -> None:
    payload = sync_reports(session_id, test_cases_sheet_url, bug_reports_sheet_url)
    print(payload)


@app.command("agent-run")
def agent_run_cmd(
    requirements: Annotated[
        list[str],
        typer.Option(
            "--requirement",
            "--requirements",
            "-r",
            help="Local requirement paths (.txt/.md/.pdf); repeat flag for multiple files",
        ),
    ] = [],
    requirement_url: Annotated[list[str], typer.Option(help="Requirement URL")] = [],
    figma_file_key: Annotated[str | None, typer.Option(help="Figma file key (optional; omit if design is only in Cursor/MCP)")] = None,
    target_url: Annotated[str | None, typer.Option(help="Target web app URL")] = None,
    out_dir: Annotated[str | None, typer.Option(help="Optional output directory for summary file")] = None,
    max_cases: Annotated[
        int | None,
        typer.Option(help="How many checklist items or test cases to generate; overrides config defaults"),
    ] = None,
    with_bug_drafts: Annotated[
        bool,
        typer.Option("--with-bug-drafts", help="Дополнительно сгенерировать черновики баг-репортов (LLM)."),
    ] = False,
    skip_test_analysis: Annotated[
        bool,
        typer.Option("--skip-test-analysis", help="Пропустить LLM шаг тест-анализа (быстрее, один запрос на артефакт)."),
    ] = False,
    output: Annotated[
        str,
        typer.Option("--output", help="Какой артефакт сгенерировать: testcases или checklist."),
    ] = "testcases",
    session_label: Annotated[
        str | None,
        typer.Option(
            "--session-label",
            "-L",
            help="Метка в имени папки сессии (sessions_dir в конфиге, по умолчанию runs/)",
        ),
    ] = None,
) -> None:
    payload = agent_run(
        requirements,
        requirement_url,
        figma_file_key,
        target_url=target_url,
        out_dir=out_dir,
        max_cases=max_cases,
        with_bug_drafts=with_bug_drafts,
        skip_test_analysis=True if skip_test_analysis else None,
        session_label=session_label,
        artifact_type="checklist" if output == "checklist" else "testcases",
    )
    print(payload)


if __name__ == "__main__":
    app()
