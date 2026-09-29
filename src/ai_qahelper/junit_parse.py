from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path


def parse_junit_failure_messages(junit_path: Path) -> dict[str, str]:
    """
    Из junit.xml pytest: ключ — имя тестовой функции (как в отчёте), значение — текст failure/error.
    """
    out: dict[str, str] = {}
    if not junit_path.is_file():
        return out
    try:
        tree = ET.parse(junit_path)
    except ET.ParseError:
        return out
    root = tree.getroot()
    # Поддержка <testsuites> и одиночного <testsuite>
    suites = root.findall("testsuite") if root.tag != "testsuite" else [root]
    for suite in suites:
        for case in suite.findall("testcase"):
            name = (case.get("name") or "").strip()
            if not name:
                continue
            msg_parts: list[str] = []
            for tag in ("failure", "error"):
                el = case.find(tag)
                if el is None:
                    continue
                m = el.get("message") or ""
                t = (el.text or "").strip()
                chunk = m if m else t
                if chunk:
                    msg_parts.append(chunk[:4000])
            if msg_parts:
                out[name] = "\n".join(msg_parts)
    return out


def pytest_name_to_case_id(pytest_func_name: str) -> str | None:
    """
    test_tc_001 -> TC-001; test_my_case -> MY-CASE (best-effort).
    """
    name = pytest_func_name.strip()
    if name.startswith("test_"):
        name = name[5:]
    if not name:
        return None
    # tc_001 -> TC-001
    m = re.match(r"^tc_([a-z0-9_]+)$", name, re.I)
    if m:
        rest = m.group(1).upper().replace("_", "-")
        return f"TC-{rest}" if not rest.startswith("TC-") else rest
    return name.upper().replace("_", "-")
