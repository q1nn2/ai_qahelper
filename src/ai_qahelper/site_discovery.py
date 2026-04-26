from __future__ import annotations

from collections import deque
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urldefrag, urljoin, urlparse
from xml.etree import ElementTree

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
SUGGESTED_TEST_AREAS = [
    "smoke",
    "navigation",
    "forms validation",
    "UI consistency",
    "accessibility basics",
    "error handling",
]
LIMITATIONS = [
    "No product requirements were provided",
    "Business rules were not verified",
    "Only visible UI was analyzed",
    "Discovery is read-only: forms are not submitted and destructive actions are not performed",
]
QA_LINK_KEYWORDS = (
    "login",
    "вход",
    "sign in",
    "signin",
    "register",
    "регистрация",
    "catalog",
    "каталог",
    "cart",
    "корзина",
    "checkout",
    "оформление",
    "order",
    "заказ",
    "payment",
    "оплата",
    "profile",
    "профиль",
    "search",
    "поиск",
    "contacts",
    "контакты",
    "feedback",
    "support",
)
SKIPPED_EXTENSIONS = (
    ".pdf",
    ".zip",
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".webp",
    ".svg",
    ".ico",
    ".css",
    ".js",
    ".woff",
    ".woff2",
)


def discover_site(
    target_url: str,
    session_label: str | None = None,
    *,
    max_pages: int = 5,
    same_domain_only: bool = True,
    max_depth: int = 1,
    timeout_seconds: int = 20,
    use_playwright: bool = True,
    create_screenshots: bool = True,
) -> SessionState:
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

    site_model = collect_site_model(
        target_url,
        sdir,
        max_pages=max_pages,
        same_domain_only=same_domain_only,
        max_depth=max_depth,
        timeout_seconds=timeout_seconds,
        use_playwright=use_playwright,
        create_screenshots=create_screenshots,
    )
    site_model_path = sdir / "site-model.json"
    save_json(site_model_path, site_model)

    exploratory_report = build_exploratory_report(site_model)
    exploratory_report_path = sdir / "exploratory-report.json"
    save_json(exploratory_report_path, exploratory_report)
    exploratory_report_md_path = sdir / "exploratory-report.md"
    exploratory_report_md_path.write_text(build_exploratory_report_markdown(exploratory_report, site_model), encoding="utf-8")

    unified = UnifiedRequirementModel(
        requirements=[
            RequirementItem(
                source=f"site-discovery:{target_url}",
                content=_site_model_to_synthetic_requirement(site_model, exploratory_report),
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
        exploratory_report_path=str(exploratory_report_path),
        exploratory_report_md_path=str(exploratory_report_md_path),
        unified_model_path=str(unified_model_path),
    )
    save_session(state)
    return state


def collect_site_model(
    target_url: str,
    session_dir: Path | None = None,
    *,
    max_pages: int = 5,
    same_domain_only: bool = True,
    max_depth: int = 1,
    timeout_seconds: int = 20,
    use_playwright: bool = True,
    create_screenshots: bool = True,
) -> dict:
    max_pages = max(1, min(max_pages, 20))
    max_depth = max(0, min(max_depth, 3))
    timeout_seconds = max(1, min(timeout_seconds, 60))
    root_url = _normalize_url(target_url)
    root_netloc = urlparse(root_url).netloc
    robots = _fetch_robots(root_url, timeout_seconds=timeout_seconds)
    sitemap_urls = _discover_sitemap_urls(
        root_url,
        robots.get("sitemaps", []),
        root_netloc=root_netloc,
        same_domain_only=same_domain_only,
        timeout_seconds=timeout_seconds,
    )
    queue: deque[tuple[str, int]] = deque(
        (url, 0) for url in _prioritize_urls([root_url, *sitemap_urls], root_url=root_url)
    )
    visited: set[str] = set()
    pages: list[dict] = []
    playwright_session = _open_playwright_session() if use_playwright else None

    try:
        while queue and len(pages) < max_pages:
            current_url, depth = queue.popleft()
            if current_url in visited:
                continue
            if not _should_visit_url(
                current_url,
                root_netloc=root_netloc,
                same_domain_only=same_domain_only,
                disallow_rules=robots.get("disallow", []),
            ):
                continue
            visited.add(current_url)
            page = _collect_page(
                current_url,
                session_dir,
                timeout_seconds=timeout_seconds,
                playwright_session=playwright_session,
                create_screenshots=create_screenshots,
                page_index=len(pages) + 1,
            )
            pages.append(page)
            if depth >= max_depth:
                continue
            candidates = [link.get("href", "") for link in page.get("links", [])]
            for next_url in _prioritize_urls(candidates, root_url=root_url):
                if not _should_visit_url(
                    next_url,
                    root_netloc=root_netloc,
                    same_domain_only=same_domain_only,
                    disallow_rules=robots.get("disallow", []),
                ):
                    continue
                if next_url not in visited:
                    queue.append((next_url, depth + 1))
    finally:
        _close_playwright_session(playwright_session)

    return {
        "target_url": target_url,
        "title": pages[0].get("title", "") if pages else "",
        "pages": pages,
        "summary": _build_summary(pages),
        "crawl": {
            "max_pages": max_pages,
            "max_depth": max_depth,
            "same_domain_only": same_domain_only,
            "robots_disallow_count": len(robots.get("disallow", [])),
            "sitemap_urls_considered": len(sitemap_urls),
            "safe_mode": "read-only",
        },
        "discovery_notes": DISCOVERY_NOTES,
    }


def build_exploratory_report(site_model: dict) -> dict:
    pages = site_model.get("pages", [])
    accessibility_risks = _accessibility_risks(site_model)
    return {
        "target_url": site_model.get("target_url", ""),
        "scope": "Site discovery without product requirements",
        "safe_mode": "read-only: no forms submitted, no submit buttons clicked, no data changed",
        "pages_scanned": [page.get("url", "") for page in pages],
        "observed_features": _observed_features(pages),
        "forms_inventory": _forms_inventory(pages),
        "navigation_inventory": _navigation_inventory(pages),
        "accessibility_risks": accessibility_risks,
        "risks_and_gaps": list(dict.fromkeys([*_risks_and_gaps(site_model), *accessibility_risks])),
        "suggested_test_areas": SUGGESTED_TEST_AREAS,
        "limitations": LIMITATIONS,
    }


def build_exploratory_report_markdown(report: dict, site_model: dict) -> str:
    pages = site_model.get("pages", [])
    page_lines = [
        f"- {page.get('url', '')} (status: {page.get('status_code', '')}, title: {page.get('title', '')})"
        for page in pages
    ]
    form_lines = [
        f"- {item.get('page_url', '')}: method={item.get('method', '')}, action={item.get('action', '')}, inputs={len(item.get('inputs', []))}"
        for item in report.get("forms_inventory", [])
    ]
    field_lines = [
        f"- {page.get('url', '')}: "
        + ", ".join(
            field.get("label")
            or field.get("aria_label")
            or field.get("placeholder")
            or field.get("name")
            or field.get("tag", "unnamed")
            for field in page.get("inputs", [])
        )
        for page in pages
        if page.get("inputs")
    ]
    button_lines = [
        f"- {page.get('url', '')}: {', '.join(page.get('buttons', []))}"
        for page in pages
        if page.get("buttons")
    ]
    error_lines = [
        f"- {page.get('url', '')}: console={len(page.get('console_errors', []))}, network={len(page.get('network_errors', []))}"
        for page in pages
        if page.get("console_errors") or page.get("network_errors")
    ]
    accessibility_lines = [f"- {risk}" for risk in report.get("accessibility_risks", [])]
    lines = [
        "# Exploratory Site Discovery Report",
        "",
        "Это анализ фактического UI, не требования продукта.",
        "",
        "## Цель анализа",
        "Site discovery without product requirements. Режим read-only: формы не отправлялись, submit/destructive actions не выполнялись.",
        "",
        "## Просканированные страницы",
        *(page_lines or ["- Не найдены"]),
        "",
        "## Найденные формы",
        *(form_lines or ["- Не найдены"]),
        "",
        "## Найденные поля",
        *(field_lines or ["- Не найдены"]),
        "",
        "## Найденные кнопки",
        *(button_lines or ["- Не найдены"]),
        "",
        "## Ошибки console/network",
        *(error_lines or ["- Не найдены"]),
        "",
        "## Accessibility Risks",
        *(accessibility_lines or ["- Не найдены автоматическим discovery"]),
        "",
        "## Suggested Test Areas",
        *[f"- {area}" for area in report.get("suggested_test_areas", [])],
        "",
        "## Limitations",
        *[f"- {item}" for item in report.get("limitations", [])],
        "",
    ]
    return "\n".join(lines)


def _fetch_robots(root_url: str, *, timeout_seconds: int) -> dict:
    robots_url = urljoin(root_url, "/robots.txt")
    try:
        with httpx.Client(timeout=timeout_seconds, follow_redirects=True) as client:
            response = client.get(robots_url)
        if response.status_code >= 400:
            return {"disallow": [], "sitemaps": []}
        return _parse_robots(response.text)
    except Exception:  # noqa: BLE001 - robots is advisory for this MVP
        return {"disallow": [], "sitemaps": []}


def _parse_robots(text: str) -> dict:
    disallow: list[str] = []
    sitemaps: list[str] = []
    applies_to_star = False
    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        key, value = [part.strip() for part in line.split(":", 1)]
        key = key.lower()
        if key == "user-agent":
            applies_to_star = value == "*"
        elif key == "disallow" and applies_to_star and value:
            disallow.append(value)
        elif key == "sitemap" and value:
            sitemaps.append(value)
    return {"disallow": disallow, "sitemaps": sitemaps}


def _discover_sitemap_urls(
    root_url: str,
    robots_sitemaps: list[str],
    *,
    root_netloc: str,
    same_domain_only: bool,
    timeout_seconds: int,
) -> list[str]:
    sitemap_urls = robots_sitemaps or [urljoin(root_url, "/sitemap.xml")]
    urls: list[str] = []
    for sitemap_url in sitemap_urls[:3]:
        try:
            with httpx.Client(timeout=timeout_seconds, follow_redirects=True) as client:
                response = client.get(sitemap_url)
            if response.status_code >= 400:
                continue
            urls.extend(_parse_sitemap(response.text))
        except Exception:  # noqa: BLE001 - sitemap is optional
            continue
    return [
        url
        for url in _prioritize_urls(urls, root_url=root_url)
        if _should_visit_url(url, root_netloc=root_netloc, same_domain_only=same_domain_only)
    ]


def _parse_sitemap(text: str) -> list[str]:
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError:
        return []
    urls: list[str] = []
    for node in root.iter():
        if node.tag.endswith("loc") and node.text:
            urls.append(_normalize_url(node.text))
    return urls


def _validate_target_url(target_url: str) -> None:
    cfg = load_config()
    allowed = [urlparse(e.base_url.unicode_string()).netloc for e in cfg.envs]
    target_netloc = urlparse(target_url).netloc
    if allowed and target_netloc not in allowed:
        raise RuntimeError(f"Target URL '{target_url}' is not in allowed environments: {allowed}")


def _collect_page(
    target_url: str,
    session_dir: Path | None,
    *,
    timeout_seconds: int,
    playwright_session: dict | None,
    create_screenshots: bool,
    page_index: int,
) -> dict:
    page = None
    if playwright_session:
        page = _collect_with_playwright(
            target_url,
            session_dir,
            playwright_session=playwright_session,
            timeout_seconds=timeout_seconds,
            create_screenshots=create_screenshots,
            page_index=page_index,
        )
    if page is None:
        page = _collect_with_httpx(target_url, timeout_seconds=timeout_seconds)
    return page


def _open_playwright_session() -> dict | None:
    try:
        from playwright.sync_api import sync_playwright
    except Exception:  # noqa: BLE001 - Playwright is optional
        return None
    manager = None
    try:
        manager = sync_playwright()
        playwright = manager.start()
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context()
        return {"manager": manager, "browser": browser, "context": context}
    except Exception:  # noqa: BLE001 - discovery falls back to httpx
        try:
            manager.stop()
        except Exception:  # noqa: BLE001
            pass
        return None


def _close_playwright_session(session: dict | None) -> None:
    if not session:
        return
    for key in ("context", "browser"):
        try:
            session[key].close()
        except Exception:  # noqa: BLE001
            pass
    try:
        session["manager"].stop()
    except Exception:  # noqa: BLE001
        pass


def _collect_with_playwright(
    target_url: str,
    session_dir: Path | None,
    *,
    playwright_session: dict,
    timeout_seconds: int,
    create_screenshots: bool,
    page_index: int,
) -> dict | None:
    console_errors: list[str] = []
    network_errors: list[str] = []
    screenshot_path = ""
    try:
        page = playwright_session["context"].new_page()
        page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
        page.on("requestfailed", lambda req: network_errors.append(req.url))
        response = page.goto(target_url, wait_until="networkidle", timeout=timeout_seconds * 1000)
        if create_screenshots and session_dir is not None:
            screenshot = session_dir / f"site-discovery-page-{page_index}.png"
            page.screenshot(path=str(screenshot), full_page=True)
            screenshot_path = str(screenshot)
        html = page.content()
        visible_text = page.locator("body").inner_text(timeout=5_000) if page.locator("body").count() else ""
        title = page.title()
        page.close()
    except Exception:  # noqa: BLE001 - browser collection should gracefully fall back
        return None

    parsed = _parse_html(target_url, html, status_code=response.status if response else None)
    parsed["title"] = title or parsed["title"]
    parsed["visible_text_sample"] = _sample_text(visible_text)
    parsed["console_errors"] = console_errors
    parsed["network_errors"] = network_errors
    parsed["screenshot_path"] = screenshot_path
    return parsed


def _collect_with_httpx(target_url: str, *, timeout_seconds: int) -> dict:
    try:
        with httpx.Client(timeout=timeout_seconds, follow_redirects=True) as client:
            response = client.get(target_url)
        return _parse_html(str(response.url), response.text, status_code=response.status_code)
    except Exception as exc:  # noqa: BLE001 - discovery should still produce a model
        return _empty_page(target_url, network_errors=[f"{type(exc).__name__}: {exc}"])


def _parse_html(page_url: str, html: str, status_code: int | None = None) -> dict:
    if BeautifulSoup is None:
        return _parse_html_fallback(page_url, html, status_code=status_code)

    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.get_text(strip=True) if soup.title else ""
    html_node = soup.find("html")
    html_lang = str(html_node.get("lang", "")).strip() if html_node else ""
    meta_description = ""
    meta = soup.find("meta", attrs={"name": "description"})
    if meta and meta.get("content"):
        meta_description = str(meta["content"]).strip()

    images_alt = [str(img.get("alt", "")).strip() for img in soup.find_all("img") if str(img.get("alt", "")).strip()]
    images_missing_alt = sum(1 for img in soup.find_all("img") if not str(img.get("alt", "")).strip())
    headings = _heading_items(soup.find_all(["h1", "h2", "h3"]))
    return {
        "url": page_url,
        "page_url": page_url,
        "title": title,
        "status_code": status_code,
        "html_lang": html_lang,
        "meta_description": meta_description,
        "headings": [item["text"] for item in headings],
        "heading_items": headings,
        "links": _links(soup, page_url),
        "forms": _forms(soup),
        "inputs": _inputs(soup),
        "buttons": _buttons(soup),
        "buttons_missing_text": _buttons_missing_text(soup),
        "links_without_text": _links_without_text(soup),
        "images_alt": images_alt,
        "images_missing_alt": images_missing_alt,
        "visible_text_sample": _sample_text(soup.get_text(" ", strip=True)),
        "console_errors": [],
        "network_errors": [],
        "screenshot_path": "",
    }


def _texts(nodes) -> list[str]:
    return [node.get_text(" ", strip=True) for node in nodes if node.get_text(" ", strip=True)]


def _heading_items(nodes) -> list[dict]:
    return [
        {"level": int(node.name[1]), "text": node.get_text(" ", strip=True)}
        for node in nodes
        if node.name in {"h1", "h2", "h3"} and node.get_text(" ", strip=True)
    ]


def _links(soup: Any, page_url: str) -> list[dict]:
    links: list[dict] = []
    for anchor in soup.find_all("a"):
        href = str(anchor.get("href", "")).strip()
        text = anchor.get_text(" ", strip=True)
        if href or text:
            links.append({"text": text, "href": _normalize_url(urljoin(page_url, href)) if href else ""})
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
                "has_submit_button": _has_submit_button(form),
            }
        )
    return forms[:100]


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
                "aria_label": str(node.get("aria-label", "")).strip(),
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


def _buttons_missing_text(soup: Any) -> int:
    missing = 0
    for node in soup.find_all("button"):
        if not node.get_text(" ", strip=True) and not str(node.get("aria-label", "")).strip():
            missing += 1
    return missing


def _has_submit_button(soup: Any) -> bool:
    for node in soup.find_all(["button", "input"]):
        node_type = str(node.get("type", "")).lower()
        if node.name == "button" and node_type in {"", "submit"}:
            return True
        if node.name == "input" and node_type == "submit":
            return True
    return False


def _links_without_text(soup: Any) -> int:
    missing = 0
    for node in soup.find_all("a"):
        if str(node.get("href", "")).strip() and not node.get_text(" ", strip=True) and not str(node.get("aria-label", "")).strip():
            missing += 1
    return missing


def _label_for_input(soup: Any, node: Any) -> str:
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
        self.html_lang = ""
        self.meta_description = ""
        self.headings: list[str] = []
        self.heading_items: list[dict] = []
        self.links: list[dict] = []
        self.links_without_text = 0
        self.forms: list[dict] = []
        self.inputs: list[dict] = []
        self.buttons: list[str] = []
        self.buttons_missing_text = 0
        self.images_alt: list[str] = []
        self.images_missing_alt = 0
        self.text_parts: list[str] = []
        self._current_link: dict | None = None
        self._current_button: list[str] | None = None
        self._current_heading: list[str] | None = None
        self._current_title: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = {key.lower(): value or "" for key, value in attrs}
        if tag == "html":
            self.html_lang = attrs_dict.get("lang", "").strip()
        elif tag == "title":
            self._current_title = []
        elif tag in {"h1", "h2", "h3"}:
            self._current_heading = []
        elif tag == "a":
            self._current_link = {"text": "", "href": _normalize_url(urljoin(self.page_url, attrs_dict.get("href", "")))}
        elif tag == "button":
            self._current_button = []
        elif tag == "form":
            self.forms.append(
                {
                    "action": attrs_dict.get("action", ""),
                    "method": attrs_dict.get("method", "get").lower(),
                    "inputs": [],
                    "buttons": [],
                    "has_submit_button": False,
                }
            )
        elif tag in {"input", "textarea", "select"}:
            item = {
                "tag": tag,
                "type": attrs_dict.get("type", ""),
                "name": attrs_dict.get("name", ""),
                "placeholder": attrs_dict.get("placeholder", ""),
                "label": "",
                    "aria_label": attrs_dict.get("aria-label", ""),
            }
            self.inputs.append(item)
            if self.forms:
                self.forms[-1]["inputs"].append(item)
                if attrs_dict.get("type", "").lower() == "submit":
                    self.forms[-1]["has_submit_button"] = True
            if (
                tag == "input"
                and attrs_dict.get("type", "").lower() in {"button", "submit", "reset"}
                and attrs_dict.get("value", "")
            ):
                self.buttons.append(attrs_dict["value"])
        elif tag == "img":
            alt = attrs_dict.get("alt", "").strip()
            if alt:
                self.images_alt.append(alt)
            else:
                self.images_missing_alt += 1
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
                self.heading_items.append({"level": int(tag[1]), "text": heading})
            self._current_heading = None
        elif tag == "a" and self._current_link is not None:
            if self._current_link.get("href") and not self._current_link.get("text"):
                self.links_without_text += 1
            self.links.append(self._current_link)
            self._current_link = None
        elif tag == "button" and self._current_button is not None:
            label = " ".join(self._current_button).strip()
            if label:
                self.buttons.append(label)
                if self.forms:
                    self.forms[-1]["buttons"].append(label)
                    self.forms[-1]["has_submit_button"] = True
            else:
                self.buttons_missing_text += 1
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
        "html_lang": parser.html_lang,
        "meta_description": parser.meta_description,
        "headings": parser.headings[:100],
        "heading_items": parser.heading_items[:100],
        "links": parser.links[:100],
        "forms": parser.forms[:100],
        "inputs": parser.inputs[:100],
        "buttons": parser.buttons[:100],
        "buttons_missing_text": parser.buttons_missing_text,
        "links_without_text": parser.links_without_text,
        "images_alt": parser.images_alt[:100],
        "images_missing_alt": parser.images_missing_alt,
        "visible_text_sample": _sample_text(" ".join(parser.text_parts)),
        "console_errors": [],
        "network_errors": [],
        "screenshot_path": "",
    }


def _empty_page(url: str, *, network_errors: list[str] | None = None) -> dict:
    return {
        "url": url,
        "page_url": url,
        "title": "",
        "status_code": None,
        "html_lang": "",
        "meta_description": "",
        "headings": [],
        "heading_items": [],
        "links": [],
        "forms": [],
        "inputs": [],
        "buttons": [],
        "buttons_missing_text": 0,
        "links_without_text": 0,
        "images_alt": [],
        "images_missing_alt": 0,
        "visible_text_sample": "",
        "console_errors": [],
        "network_errors": network_errors or [],
        "screenshot_path": "",
    }


def _normalize_url(url: str) -> str:
    clean, _fragment = urldefrag((url or "").strip())
    parsed = urlparse(clean)
    if parsed.scheme and parsed.netloc:
        return parsed._replace(path=parsed.path or "/").geturl().rstrip("/") or clean
    return clean


def _should_visit_url(
    url: str,
    *,
    root_netloc: str,
    same_domain_only: bool,
    disallow_rules: list[str] | None = None,
) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return False
    if same_domain_only and parsed.netloc != root_netloc:
        return False
    path = parsed.path.lower()
    if path.endswith(SKIPPED_EXTENSIONS):
        return False
    for rule in disallow_rules or []:
        if rule and parsed.path.startswith(rule):
            return False
    return True


def _prioritize_urls(urls: list[str], *, root_url: str) -> list[str]:
    normalized = list(dict.fromkeys(_normalize_url(urljoin(root_url, url)) for url in urls if url))
    root = _normalize_url(root_url)
    return sorted(
        normalized,
        key=lambda url: (
            0 if url == root else _qa_link_priority(url),
            len(url),
            url,
        ),
    )


def _qa_link_priority(url: str, text: str = "") -> int:
    haystack = f"{url} {text}".lower().replace("-", " ").replace("_", " ")
    return 1 if any(keyword in haystack for keyword in QA_LINK_KEYWORDS) else 2


def _build_summary(pages: list[dict]) -> dict:
    return {
        "pages_scanned": len(pages),
        "forms_found": sum(len(page.get("forms", [])) for page in pages),
        "inputs_found": sum(len(page.get("inputs", [])) for page in pages),
        "buttons_found": sum(len(page.get("buttons", [])) for page in pages),
        "links_found": sum(len(page.get("links", [])) for page in pages),
        "console_errors_found": sum(len(page.get("console_errors", [])) for page in pages),
        "network_errors_found": sum(len(page.get("network_errors", [])) for page in pages),
    }


def _observed_features(pages: list[dict]) -> list[str]:
    features: list[str] = []
    for page in pages:
        prefix = page.get("title") or page.get("url")
        if page.get("headings"):
            features.append(f"{prefix}: headings: {', '.join(page['headings'][:5])}")
        if page.get("forms"):
            features.append(f"{prefix}: {len(page['forms'])} form(s)")
        if page.get("buttons"):
            features.append(f"{prefix}: buttons: {', '.join(page['buttons'][:5])}")
    return features


def _forms_inventory(pages: list[dict]) -> list[dict]:
    inventory: list[dict] = []
    for page in pages:
        for form in page.get("forms", []):
            inventory.append(
                {
                    "page_url": page.get("url", ""),
                    "method": form.get("method", ""),
                    "action": form.get("action", ""),
                    "inputs": form.get("inputs", []),
                    "buttons": form.get("buttons", []),
                }
            )
    return inventory


def _navigation_inventory(pages: list[dict]) -> list[dict]:
    return [
        {
            "page_url": page.get("url", ""),
            "links": page.get("links", [])[:30],
        }
        for page in pages
    ]


def _accessibility_risks(site_model: dict) -> list[str]:
    risks: list[str] = []
    for page in site_model.get("pages", []):
        url = page.get("url", "")
        if not page.get("html_lang"):
            risks.append(f"{url}: html lang is missing")
        if page.get("images_missing_alt", 0):
            risks.append(f"{url}: image without alt text")
        for input_item in page.get("inputs", []):
            if not (input_item.get("label") or input_item.get("aria_label")):
                risks.append(f"{url}: input/select/textarea without label or aria-label")
        if page.get("buttons_missing_text", 0):
            risks.append(f"{url}: button without text or aria-label")
        if page.get("links_without_text", 0):
            risks.append(f"{url}: link without text or aria-label")
        for form in page.get("forms", []):
            if not form.get("has_submit_button"):
                risks.append(f"{url}: form without submit button")
        h1_count = sum(1 for item in page.get("heading_items", []) if item.get("level") == 1)
        if h1_count == 0:
            risks.append(f"{url}: missing h1")
        elif h1_count > 1:
            risks.append(f"{url}: multiple h1 headings")
        if _has_broken_heading_hierarchy(page.get("heading_items", [])):
            risks.append(f"{url}: broken h1/h2/h3 hierarchy")
    return list(dict.fromkeys(risks))


def _has_broken_heading_hierarchy(headings: list[dict]) -> bool:
    previous = 0
    for heading in headings:
        level = int(heading.get("level", 0))
        if previous and level > previous + 1:
            return True
        previous = level
    return False


def _risks_and_gaps(site_model: dict) -> list[str]:
    risks: list[str] = []
    for page in site_model.get("pages", []):
        url = page.get("url", "")
        if page.get("status_code") and page.get("status_code") != 200:
            risks.append(f"{url}: non-200 status code {page.get('status_code')}")
        if not page.get("meta_description"):
            risks.append(f"{url}: missing meta description")
        if page.get("console_errors"):
            risks.append(f"{url}: console errors found")
        if page.get("network_errors"):
            risks.append(f"{url}: network failures found")
        if page.get("images_missing_alt", 0):
            risks.append(f"{url}: images without alt text: {page.get('images_missing_alt')}")
        for input_item in page.get("inputs", []):
            if not (input_item.get("label") or input_item.get("aria_label") or input_item.get("placeholder") or input_item.get("name")):
                risks.append(f"{url}: input without label/name/placeholder")
            elif not (input_item.get("label") or input_item.get("aria_label")):
                risks.append(f"{url}: form input without explicit label: {input_item.get('name') or input_item.get('placeholder')}")
        if page.get("buttons_missing_text", 0):
            risks.append(f"{url}: button without visible text")
    return list(dict.fromkeys(risks))


def _sample_text(text: str, limit: int = 4000) -> str:
    normalized = " ".join(text.split())
    return normalized[:limit]


def _site_model_to_synthetic_requirement(site_model: dict, exploratory_report: dict) -> str:
    pages = site_model.get("pages", [])
    page_lines = [
        f"- {page.get('url', '')} | title={page.get('title', '')} | status={page.get('status_code', '')}"
        for page in pages
    ]
    form_lines = [
        f"- {item.get('page_url', '')}: method={item.get('method', '')}, action={item.get('action', '')}, inputs={len(item.get('inputs', []))}"
        for item in exploratory_report.get("forms_inventory", [])
    ]
    field_lines = [
        f"- {page.get('url', '')}: "
        + ", ".join(
            (field.get("label") or field.get("placeholder") or field.get("name") or field.get("tag") or "unnamed")
            for field in page.get("inputs", [])[:20]
        )
        for page in pages
        if page.get("inputs")
    ]
    button_lines = [
        f"- {page.get('url', '')}: {', '.join(page.get('buttons', [])[:20])}"
        for page in pages
        if page.get("buttons")
    ]
    link_lines = [
        f"- {page.get('url', '')}: "
        + ", ".join((link.get("text") or link.get("href") or "") for link in page.get("links", [])[:20])
        for page in pages
        if page.get("links")
    ]
    risks = exploratory_report.get("risks_and_gaps", [])
    return "\n".join(
        [
            "Это не требования продукта. Это фактическое описание сайта, полученное автоматическим discovery. Не придумывай бизнес-требования.",
            f"Целевой URL: {site_model.get('target_url', '')}",
            f"Summary: {site_model.get('summary', {})}",
            "",
            "Страницы:",
            *(page_lines or ["- не найдены"]),
            "",
            "Найденные формы:",
            *(form_lines or ["- не найдены"]),
            "",
            "Найденные поля:",
            *(field_lines or ["- не найдены"]),
            "",
            "Найденные кнопки:",
            *(button_lines or ["- не найдены"]),
            "",
            "Основные ссылки:",
            *(link_lines or ["- не найдены"]),
            "",
            "Потенциальные риски:",
            *(risks or ["- существенные UI-риски не выявлены автоматическим discovery"]),
            "",
            "Генерируй только exploratory/smoke/UI тест-кейсы по наблюдаемому поведению сайта.",
        ]
    )
