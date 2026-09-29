from __future__ import annotations

import subprocess
from pathlib import Path

from ai_qahelper.models import AutoExecutionResult, ManualExecutionResult, TestCase
from ai_qahelper.reporting import format_steps_for_export


def run_manual_cases(test_cases: list[TestCase], evidence_dir: Path) -> list[ManualExecutionResult]:
    evidence_dir.mkdir(parents=True, exist_ok=True)
    results: list[ManualExecutionResult] = []
    for case in test_cases:
        checklist = evidence_dir / f"{case.case_id}-manual-checklist.md"
        steps_md = "\n".join(f"- {line}" for line in format_steps_for_export(case.steps).split("\n"))
        checklist.write_text("\n".join([f"# {case.title}", "## Шаги", steps_md]), encoding="utf-8")
        results.append(
            ManualExecutionResult(
                test_case_id=case.case_id,
                status="blocked",
                notes="Manual execution template generated. Marked blocked until interactive run.",
                evidence_files=[str(checklist)],
            )
        )
    return results


def generate_playwright_pytest_tests(test_cases: list[TestCase], output_dir: Path, base_url: str) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    generated: list[Path] = []
    for case in test_cases:
        safe_id = case.case_id.lower().replace("-", "_")
        file_path = output_dir / f"test_{safe_id}.py"
        file_path.write_text(
            _test_template(case.case_id, case.title, case.steps, base_url),
            encoding="utf-8",
        )
        generated.append(file_path)
    return generated


def _test_template(case_id: str, title: str, steps: list[str], base_url: str) -> str:
    step_comment = "\n".join([f"    # - {s}" for s in steps])
    return f'''from playwright.sync_api import sync_playwright


def test_{case_id.lower().replace("-", "_")}():
    """{title}"""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto("{base_url}", wait_until="networkidle")
{step_comment}
        assert page.url.startswith("{base_url}")
        browser.close()
'''


def run_pytest_suite(project_root: Path, test_dir: Path, reports_dir: Path) -> tuple[int, Path, Path]:
    reports_dir.mkdir(parents=True, exist_ok=True)
    junit = reports_dir / "junit.xml"
    html = reports_dir / "report.html"
    cmd = [
        "python",
        "-m",
        "pytest",
        str(test_dir),
        f"--junitxml={junit}",
        f"--html={html}",
        "--self-contained-html",
    ]
    proc = subprocess.run(cmd, cwd=project_root, capture_output=True, text=True)
    (reports_dir / "pytest.stdout.log").write_text(proc.stdout or "", encoding="utf-8")
    (reports_dir / "pytest.stderr.log").write_text(proc.stderr or "", encoding="utf-8")
    return proc.returncode, junit, html


def synthesize_auto_results(test_cases: list[TestCase], test_files: list[Path], return_code: int) -> list[AutoExecutionResult]:
    status = "passed" if return_code == 0 else "failed"
    file_map = {p.stem.replace("test_", "").upper().replace("_", "-"): p for p in test_files}
    results: list[AutoExecutionResult] = []
    for tc in test_cases:
        key = tc.case_id.upper()
        test_file = file_map.get(key)
        results.append(
            AutoExecutionResult(
                test_case_id=tc.case_id,
                status=status if test_file else "skipped",
                test_file=str(test_file) if test_file else "",
                error=None if return_code == 0 else "pytest run reported failures",
                artifacts=[],
            )
        )
    return results
