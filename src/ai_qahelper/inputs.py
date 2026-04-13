from __future__ import annotations

import os
from pathlib import Path

import httpx
from pypdf import PdfReader

from ai_qahelper.llm_client import LlmClient
from ai_qahelper.models import AppConfig, DesignModel, DesignNode, RequirementItem
from ai_qahelper.pdf_vision import build_pdf_requirement_content


def parse_requirements(paths: list[str], app_cfg: AppConfig | None = None) -> list[RequirementItem]:
    items: list[RequirementItem] = []
    llm: LlmClient | None = None
    if app_cfg and app_cfg.pdf_vision and any(Path(p).suffix.lower() == ".pdf" for p in paths):
        llm = LlmClient(app_cfg.llm)

    for path in paths:
        p = Path(path)
        if not p.is_file():
            resolved = p.resolve()
            raise FileNotFoundError(
                f"Requirement file not found: {path!r} (resolved: {resolved}, cwd: {Path.cwd()}). "
                "Check the path and filename (on Windows avoid accidental .pdf.pdf if extensions are hidden)."
            )
        if p.suffix.lower() == ".pdf" and app_cfg is not None and llm is not None:
            content = build_pdf_requirement_content(
                p,
                llm,
                app_cfg.llm,
                pdf_vision=app_cfg.pdf_vision,
            )
        else:
            content = _read_requirement_file(p)
        items.append(RequirementItem(source=str(p), content=content))
    return items


def _read_requirement_file(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        return _read_pdf_requirement(path)
    return path.read_text(encoding="utf-8")


def _read_pdf_requirement(path: Path) -> str:
    reader = PdfReader(str(path))
    chunks: list[str] = []
    for page in reader.pages:
        chunks.append(page.extract_text() or "")
    text = "\n".join(chunks).strip()
    if not text:
        return "PDF parsed but no text content was extracted."
    return text


def parse_requirement_url(url: str, timeout_s: int = 20) -> RequirementItem:
    with httpx.Client(timeout=timeout_s) as client:
        resp = client.get(url)
        resp.raise_for_status()
    return RequirementItem(source=url, content=resp.text)


def _collect_nodes(raw_node: dict, max_depth: int = 3, depth: int = 0) -> DesignNode:
    node = DesignNode(
        id=raw_node.get("id", "unknown"),
        name=raw_node.get("name", "unnamed"),
        text=raw_node.get("characters"),
        node_type=raw_node.get("type"),
    )
    if depth >= max_depth:
        return node
    for child in raw_node.get("children", [])[:50]:
        node.children.append(_collect_nodes(child, max_depth=max_depth, depth=depth + 1))
    return node


def _summarize_design(model: DesignModel) -> tuple[int, int]:
    nodes_total = 0
    text_nodes = 0
    stack = list(model.nodes)
    while stack:
        node = stack.pop()
        nodes_total += 1
        if node.text:
            text_nodes += 1
        stack.extend(node.children)
    return nodes_total, text_nodes


def ingest_figma(file_key: str, node_ids: list[str] | None = None) -> DesignModel:
    token = os.getenv("FIGMA_API_TOKEN")
    if not token:
        return DesignModel(file_key=file_key, warnings=["Missing FIGMA_API_TOKEN; skipped Figma ingestion"])

    headers = {"X-Figma-Token": token}
    with httpx.Client(timeout=30) as client:
        file_resp = client.get(f"https://api.figma.com/v1/files/{file_key}", headers=headers)
        if file_resp.status_code >= 400:
            return DesignModel(
                file_key=file_key,
                warnings=[f"Figma file fetch failed: HTTP {file_resp.status_code}"],
            )
        file_json = file_resp.json()
        model = DesignModel(file_key=file_key, file_name=file_json.get("name"))

        doc = file_json.get("document", {})
        if doc:
            model.nodes.append(_collect_nodes(doc, max_depth=5))
        else:
            model.warnings.append("Figma file has empty document tree")

        if node_ids:
            ids = ",".join(node_ids)
            nodes_resp = client.get(
                f"https://api.figma.com/v1/files/{file_key}/nodes",
                headers=headers,
                params={"ids": ids},
            )
            if nodes_resp.status_code < 400:
                nodes_payload = nodes_resp.json().get("nodes", {})
                for node_id, body in nodes_payload.items():
                    document = body.get("document")
                    if document:
                        model.nodes.append(_collect_nodes(document, max_depth=5))
            else:
                model.warnings.append(f"Figma nodes fetch failed: HTTP {nodes_resp.status_code}")
        nodes_total, text_nodes = _summarize_design(model)
        if nodes_total == 0:
            model.warnings.append("No Figma nodes were collected")
        if text_nodes == 0:
            model.warnings.append("No textual labels found in collected Figma nodes")
        return model
