from __future__ import annotations

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
) -> None:
    session_id = ingest(requirements, requirement_url, figma_file_key, target_url)
    print({"session_id": session_id})


@app.command("generate-docs")
def generate_docs_cmd(session_id: str) -> None:
    state = generate_docs(session_id)
    print({"session_id": state.session_id, "test_cases_path": state.test_cases_path, "bug_reports_path": state.bug_reports_path})


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
) -> None:
    payload = agent_run(requirements, requirement_url, figma_file_key, target_url=target_url, out_dir=out_dir)
    print(payload)


if __name__ == "__main__":
    app()
