from __future__ import annotations

from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

try:
    from bs4 import BeautifulSoup
except ModuleNotFoundError:  # pragma: no cover - dependency is declared, fallback keeps editable envs usable
    BeautifulSoup = None

from ai_qahelper.config import load_config
from ai_qahelper.logging_utils import configure_logging
from ai_qahelper.models import RequirementItem, SessionState, UnifiedRequirementModel
from ai_qahelper.reporting import save_json
from ai_qahelper.session_naming import build_session_id
from ai_qahelper.session_service import save_session, session_path

DISCOVERY_NOTES = [
    "Требования не были предоставлены",
    "Тест-кейсы основаны на фактически найденных элементах UI",
]


def discover_site(target_url: str, session_label: str | None = None) -> SessionState:
    """Create a session from observed site structure instead of product requirements."""

    _validate_target_url(target_url)
    now = datetime.now(UTC)
    session_id = build_session_id(
        created_at=now,
        target_url=target_url,
        local_requirement_paths=[],
        session_label=session_label or "site-discovery",
    )
    sdir = session_path(session_id)
    configure_logging(sdir)

    site_model = collect_site_model(target_url, sdir)
    site_model_path = sdir / "site-model.json"
    save_json(site_model_path, site_model)

    unified = UnifiedRequirementModel(
        requirements=[
            RequirementItem(
                source=f"site-discovery:{target_url}",
                content=_site_model_to_synthetic_requirement(site_model),
            )
        ],
        target_url=target_url,
    )
    unified_model_path = sdir / "unified-model.json"
    save_json(unified_model_path, unified.model_dump(mode="json"))

    state = SessionState(
        session_id=session_id,
        created_at=now,
        target_url=target_url,
        requirements_files=[],
        site_model_path=str(site_model_path),
        unified_model_path=str(unified_model_path),
    )
    save_session(state)
    return state


def collect_site_model(target_url: str, session_dir: Path | None = None) -> dict:
    page = _collect_with_playwright(target_url, session_dir)
    if page is None:
        page = _collect_with_httpx(target_url)
    return {
        "target_url": target_url,
        "title": page.get("title", ""),
        "pages": [page],
        "discovery_notes": DISCOVERY_NOTES,
    }


def _validate_target_url(target_url: str) -> None:
    cfg = load_config()
    allowed = [urlparse(e.base_url.unicode_string()).netloc for e in cfg.envs]
    target_netloc = urlparse(target_url).netloc
    if allowed and target_netloc not in allowed:
        raise RuntimeError(f"Target URL '{target_url}' is not in allowed environments: {allowed}")


def _collect_with_playwright(target_url: str, session_dir: Path | None) -> dict | None:
    try:
        from playwright.sync_api import sync_playwright
    except Exception:  # noqa: BLE001 - Playwright is optional
        return None

    console_errors: list[str] = []
    network_errors: list[str] = []
    screenshot_path = ""
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
            page.on("requestfailed", lambda req: network_errors.append(req.url))
            response = page.goto(target_url, wait_until="networkidle", timeout=30_000)
            if session_dir is not None:
                screenshot = session_dir / "site-discovery.png"
                page.screenshot(path=str(screenshot), full_page=True)
                screenshot_path = str(screenshot)
            html = page.content()
            visible_text = page.locator("body").inner_text(timeout=5_000) if page.locator("body").count() else ""
            title = page.title()
            browser.close()
    except Exception:  # noqa: BLE001 - browser collection should gracefully fall back
        return None

    parsed = _parse_html(target_url, html, status_code=response.status if response else None)
    parsed["title"] = title or parsed["title"]
    parsed["visible_text_sample"] = _sample_text(visible_text)
    parsed["console_errors"] = console_errors
    parsed["network_errors"] = network_errors
    parsed["screenshot_path"] = screenshot_path
    return parsed


def _collect_with_httpx(target_url: str) -> dict:
    with httpx.Client(timeout=20.0, follow_redirects=True) as client:
        response = client.get(target_url)
    return _parse_html(target_url, response.text, status_code=response.status_code)


def _parse_html(page_url: str, html: str, status_code: int | None = None) -> dict:
    if BeautifulSoup is None:
        return _parse_html_fallback(page_url, html, status_code=status_code)

    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.get_text(strip=True) if soup.title else ""
    meta_description = ""
    meta = soup.find("meta", attrs={"name": "description"})
    if meta and meta.get("content"):
        meta_description = str(meta["content"]).strip()

    return {
        "url": page_url,
        "page_url": page_url,
        "title": title,
        "status_code": status_code,
        "meta_description": meta_description,
        "headings": _texts(soup.find_all(["h1", "h2", "h3"])),
        "links": _links(soup, page_url),
        "forms": _forms(soup),
        "inputs": _inputs(soup),
        "buttons": _buttons(soup),
        "images_alt": [str(img.get("alt", "")).strip() for img in soup.find_all("img") if str(img.get("alt", "")).strip()],
        "visible_text_sample": _sample_text(soup.get_text(" ", strip=True)),
        "console_errors": [],
        "network_errors": [],
        "screenshot_path": "",
    }


def _texts(nodes) -> list[str]:
    return [node.get_text(" ", strip=True) for node in nodes if node.get_text(" ", strip=True)]


def _links(soup: Any, page_url: str) -> list[dict]:
    links: list[dict] = []
    for anchor in soup.find_all("a"):
        href = str(anchor.get("href", "")).strip()
        text = anchor.get_text(" ", strip=True)
        if href or text:
            links.append({"text": text, "href": urljoin(page_url, href) if href else ""})
    return links[:100]


def _forms(soup: Any) -> list[dict]:
    forms: list[dict] = []
    for form in soup.find_all("form"):
        forms.append(
            {
                "action": str(form.get("action", "")).strip(),
                "method": str(form.get("method", "get")).lower(),
                "inputs": _inputs(form),
                "buttons": _buttons(form),
            }
        )
    return forms


def _inputs(soup: Any) -> list[dict]:
    inputs: list[dict] = []
    for node in soup.find_all(["input", "textarea", "select"]):
        inputs.append(
            {
                "tag": node.name,
                "type": str(node.get("type", "")).strip(),
                "name": str(node.get("name", "")).strip(),
                "placeholder": str(node.get("placeholder", "")).strip(),
                "label": _label_for_input(soup, node),
            }
        )
    return inputs[:100]


def _buttons(soup: Any) -> list[str]:
    labels = _texts(soup.find_all("button"))
    submit_inputs = [
        str(node.get("value", "")).strip()
        for node in soup.find_all("input")
        if str(node.get("type", "")).lower() in {"button", "submit", "reset"} and str(node.get("value", "")).strip()
    ]
    return [*labels, *submit_inputs][:100]


def _label_for_input(soup: BeautifulSoup, node) -> str:
    input_id = node.get("id")
    if input_id:
        label = soup.find("label", attrs={"for": input_id})
        if label:
            return label.get_text(" ", strip=True)
    parent_label = node.find_parent("label")
    return parent_label.get_text(" ", strip=True) if parent_label else ""


class _SimpleHtmlCollector(HTMLParser):
    def __init__(self, page_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.page_url = page_url
        self.title = ""
        self.meta_description = ""
        self.headings: list[str] = []
        self.links: list[dict] = []
        self.forms: list[dict] = []
        self.inputs: list[dict] = []
        self.buttons: list[str] = []
        self.images_alt: list[str] = []
        self.text_parts: list[str] = []
        self._current_tag = ""
        self._current_link: dict | None = None
        self._current_button: list[str] | None = None
        self._current_heading: list[str] | None = None
        self._current_title: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = {key.lower(): value or "" for key, value in attrs}
        self._current_tag = tag
        if tag == "title":
            self._current_title = []
        elif tag in {"h1", "h2", "h3"}:
            self._current_heading = []
        elif tag == "a":
            self._current_link = {"text": "", "href": urljoin(self.page_url, attrs_dict.get("href", ""))}
        elif tag == "button":
            self._current_button = []
        elif tag == "form":
            self.forms.append({"action": attrs_dict.get("action", ""), "method": attrs_dict.get("method", "get").lower(), "inputs": [], "buttons": []})
        elif tag in {"input", "textarea", "select"}:
            item = {
                "tag": tag,
                "type": attrs_dict.get("type", ""),
                "name": attrs_dict.get("name", ""),
                "placeholder": attrs_dict.get("placeholder", ""),
                "label": "",
            }
            self.inputs.append(item)
            if self.forms:
                self.forms[-1]["inputs"].append(item)
            if tag == "input" and attrs_dict.get("type", "").lower() in {"button", "submit", "reset"} and attrs_dict.get("value", ""):
                self.buttons.append(attrs_dict["value"])
        elif tag == "img" and attrs_dict.get("alt", ""):
            self.images_alt.append(attrs_dict["alt"])
        elif tag == "meta" and attrs_dict.get("name", "").lower() == "description":
            self.meta_description = attrs_dict.get("content", "").strip()

    def handle_endtag(self, tag: str) -> None:
        if tag == "title" and self._current_title is not None:
            self.title = " ".join(self._current_title).strip()
            self._current_title = None
        elif tag in {"h1", "h2", "h3"} and self._current_heading is not None:
            heading = " ".join(self._current_heading).strip()
            if heading:
                self.headings.append(heading)
            self._current_heading = None
        elif tag == "a" and self._current_link is not None:
            self.links.append(self._current_link)
            self._current_link = None
        elif tag == "button" and self._current_button is not None:
            label = " ".join(self._current_button).strip()
            if label:
                self.buttons.append(label)
                if self.forms:
                    self.forms[-1]["buttons"].append(label)
            self._current_button = None

    def handle_data(self, data: str) -> None:
        text = data.strip()
        if not text:
            return
        self.text_parts.append(text)
        if self._current_title is not None:
            self._current_title.append(text)
        if self._current_heading is not None:
            self._current_heading.append(text)
        if self._current_link is not None:
            self._current_link["text"] = (self._current_link["text"] + " " + text).strip()
        if self._current_button is not None:
            self._current_button.append(text)


def _parse_html_fallback(page_url: str, html: str, status_code: int | None = None) -> dict:
    parser = _SimpleHtmlCollector(page_url)
    parser.feed(html)
    return {
        "url": page_url,
        "page_url": page_url,
        "title": parser.title,
        "status_code": status_code,
        "meta_description": parser.meta_description,
        "headings": parser.headings[:100],
        "links": parser.links[:100],
        "forms": parser.forms[:100],
        "inputs": parser.inputs[:100],
        "buttons": parser.buttons[:100],
        "images_alt": parser.images_alt[:100],
        "visible_text_sample": _sample_text(" ".join(parser.text_parts)),
        "console_errors": [],
        "network_errors": [],
        "screenshot_path": "",
    }


def _sample_text(text: str, limit: int = 4000) -> str:
    normalized = " ".join(text.split())
    return normalized[:limit]


def _site_model_to_synthetic_requirement(site_model: dict) -> str:
    page = (site_model.get("pages") or [{}])[0]
    headings = ", ".join(page.get("headings", [])[:10]) or "не найдены"
    buttons = ", ".join(page.get("buttons", [])[:10]) or "не найдены"
    links = page.get("links", [])
    link_texts = ", ".join((link.get("text") or link.get("href") or "") for link in links[:10]) or "не найдены"
    forms = page.get("forms", [])
    inputs = page.get("inputs", [])
    return "\n".join(
        [
            "Это не требования продукта. Это фактическое описание сайта, полученное автоматическим discovery.",
            f"Целевой URL: {site_model.get('target_url', '')}",
            f"Заголовок страницы: {page.get('title', '')}",
            f"HTTP status: {page.get('status_code', '')}",
            f"Meta description: {page.get('meta_description', '')}",
            f"Найденные заголовки h1/h2/h3: {headings}",
            f"Найденные кнопки: {buttons}",
            f"Найденные ссылки: {link_texts}",
            f"Количество форм: {len(forms)}",
            f"Количество полей ввода: {len(inputs)}",
            f"Ошибки console: {len(page.get('console_errors', []))}",
            f"Network failures: {len(page.get('network_errors', []))}",
            "Генерируй только exploratory/smoke/UI тест-кейсы по наблюдаемому поведению сайта. Не придумывай бизнес-требования.",
        ]
    )
