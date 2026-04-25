from __future__ import annotations

import json
from types import SimpleNamespace

from ai_qahelper.chat_agent import ChatContext, handle_message
from ai_qahelper.chat_planner import ChatPlan, PlanAction
from ai_qahelper.site_discovery import build_exploratory_report, collect_site_model, discover_site


class FakeResponse:
    def __init__(self, url: str, text: str, status_code: int = 200) -> None:
        self.url = url
        self.text = text
        self.status_code = status_code


class FakeHttpClient:
    pages: dict[str, str] = {}
    calls: list[str] = []

    def __init__(self, *args, **kwargs) -> None:
        pass

    def __enter__(self) -> "FakeHttpClient":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def get(self, url: str) -> FakeResponse:
        self.calls.append(url)
        return FakeResponse(url, self.pages[url])


def _setup_fake_pages(monkeypatch, pages: dict[str, str]) -> None:
    FakeHttpClient.pages = pages
    FakeHttpClient.calls = []
    monkeypatch.setattr("ai_qahelper.site_discovery.httpx.Client", FakeHttpClient)


def test_multi_page_crawl_respects_max_pages_and_ignores_external(monkeypatch) -> None:
    _setup_fake_pages(
        monkeypatch,
        {
            "https://example.com": """
                <html><title>Home</title><body>
                <a href="/one">One</a>
                <a href="/two">Two</a>
                <a href="/three">Three</a>
                <a href="https://external.example/out">External</a>
                <a href="/file.pdf">PDF</a>
                </body></html>
            """,
            "https://example.com/one": "<html><title>One</title><body><h1>One</h1></body></html>",
            "https://example.com/two": "<html><title>Two</title><body><h1>Two</h1></body></html>",
        },
    )

    model = collect_site_model("https://example.com", max_pages=2, max_depth=1, use_playwright=False)

    assert model["summary"]["pages_scanned"] == 2
    assert FakeHttpClient.calls == ["https://example.com", "https://example.com/one"]
    assert "https://external.example/out" not in FakeHttpClient.calls


def test_site_model_summary_counts_inventory(monkeypatch) -> None:
    _setup_fake_pages(
        monkeypatch,
        {
            "https://example.com": """
                <html><title>Home</title><body>
                <a href="/next">Next</a>
                <form method="post"><input name="email"><button>Send</button></form>
                <button>Open</button>
                </body></html>
            """,
            "https://example.com/next": """
                <html><title>Next</title><body>
                <a href="/">Home</a>
                <input placeholder="Search">
                <button>Search</button>
                </body></html>
            """,
        },
    )

    model = collect_site_model("https://example.com", max_pages=2, max_depth=1, use_playwright=False)

    assert model["summary"]["pages_scanned"] == 2
    assert model["summary"]["forms_found"] == 1
    assert model["summary"]["inputs_found"] == 2
    assert model["summary"]["buttons_found"] == 3
    assert model["summary"]["links_found"] == 2


def test_exploratory_report_file_is_created(monkeypatch, tmp_path) -> None:
    _setup_fake_pages(
        monkeypatch,
        {"https://example.com": "<html><title>Home</title><body><h1>Home</h1></body></html>"},
    )
    monkeypatch.setattr("ai_qahelper.site_discovery.load_config", lambda: SimpleNamespace(envs=[]))
    monkeypatch.setattr("ai_qahelper.site_discovery.session_path", lambda session_id: tmp_path / session_id)
    monkeypatch.setattr("ai_qahelper.site_discovery.save_session", lambda state: None)

    state = discover_site("https://example.com", max_pages=1, use_playwright=False)

    assert state.exploratory_report_path is not None
    report = json.loads((tmp_path / state.session_id / "exploratory-report.json").read_text(encoding="utf-8"))
    assert "No product requirements were provided" in report["limitations"]
    assert state.exploratory_report_path.endswith("exploratory-report.json")


def test_build_exploratory_report_contains_limitations() -> None:
    model = {
        "target_url": "https://example.com",
        "pages": [
            {
                "url": "https://example.com",
                "forms": [],
                "links": [],
                "inputs": [],
                "buttons": [],
                "console_errors": [],
                "network_errors": [],
            }
        ],
    }

    report = build_exploratory_report(model)

    assert report["scope"] == "Site discovery without product requirements"
    assert "Only visible UI was analyzed" in report["limitations"]


def test_chat_response_warns_for_site_discovery_plan() -> None:
    class FakeExecutor:
        def execute(self, context, plan, user_message=""):
            context.session_id = "site-s1"
            return [{"session_id": "site-s1", "site_model_path": "runs/site-s1/site-model.json"}]

    plan = ChatPlan(actions=[PlanAction(type="discover_site")])

    response = handle_message(
        ChatContext(target_url="https://example.com"),
        "требований нет, проанализируй сайт",
        plan=plan,
        executor=FakeExecutor(),
    )

    assert "Тест-кейсы созданы по фактическому поведению сайта, а не по требованиям." in response.message
