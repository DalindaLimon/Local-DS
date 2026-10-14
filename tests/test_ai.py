import httpx

from app import ai
from app.urlsafe import FetchResult
from tests.conftest import login, make_item, make_short, make_source, make_user


def _enable(settings):
    settings.llm_base_url = "http://10.0.0.5:11434/v1"
    settings.llm_model = "llama3.1:8b"


def test_parse_sse_line():
    assert ai.parse_sse_line('data: {"choices":[{"delta":{"content":"Hi"}}]}') == "Hi"
    assert ai.parse_sse_line("data: [DONE]") is None
    assert ai.parse_sse_line(": keepalive") is None
    assert ai.parse_sse_line('data: {"choices":[]}') is None
    assert ai.parse_sse_line("data: not json") is None


def test_state_reports_ai_and_ask_needs_config(app, conn, settings):
    make_user(conn, "a")
    c = login(app, "a")
    i = make_item(conn, make_source(conn))
    assert c.get("/api/state").json()["ai"] is False
    assert c.post("/api/ai/ask", json={"type": "item", "id": i}).status_code == 503
    _enable(settings)
    assert c.get("/api/state").json()["ai"] is True


def test_ask_streams_answer_with_post_context(app, conn, settings, monkeypatch):
    _enable(settings)
    settings.llm_fetch_article = False
    make_user(conn, "a")
    c = login(app, "a")
    i = make_item(conn, make_source(conn, "Science Daily"), "Octopuses dream")
    seen = {}

    async def fake_stream(s, messages):
        seen["messages"] = messages
        yield "Claim 1: "
        yield "plausible."

    monkeypatch.setattr(ai, "stream_chat", fake_stream)
    r = c.post("/api/ai/ask", json={"type": "item", "id": i, "mode": "factcheck", "question": "Is it new?"})
    assert r.status_code == 200 and r.text == "Claim 1: plausible."
    assert r.headers["x-ai-model"] == "llama3.1:8b"
    prompt = seen["messages"][1]["content"]
    assert "Title: Octopuses dream" in prompt and "Source: Science Daily" in prompt
    assert "Fact-check" in prompt and "Is it new?" in prompt
    assert "Never invent facts" in seen["messages"][0]["content"]
    # free question needs text; unknown items 404
    assert c.post("/api/ai/ask", json={"type": "item", "id": i, "mode": "question"}).status_code == 400
    assert c.post("/api/ai/ask", json={"type": "item", "id": 999}).status_code == 404


def test_ask_errors(app, conn, settings, monkeypatch):
    _enable(settings)
    make_user(conn, "a")
    c = login(app, "a")
    sh = make_short(conn, settings, make_source(conn, "yt", kind="youtube"), "SHORTVID001")

    async def down(s, messages):
        raise ai.AIError("Could not reach the LLM server")
        yield ""  # pragma: no cover - makes this an async generator

    monkeypatch.setattr(ai, "stream_chat", down)
    r = c.post("/api/ai/ask", json={"type": "short", "id": sh, "mode": "explain"})
    assert r.status_code == 502 and "reach" in r.json()["detail"]

    async def breaks_midway(s, messages):
        yield "Partial"
        raise ai.AIError("timeout")

    monkeypatch.setattr(ai, "stream_chat", breaks_midway)
    r = c.post("/api/ai/ask", json={"type": "short", "id": sh})
    assert r.text.startswith("Partial") and "[AI error: timeout]" in r.text


def test_article_text_uses_safe_get_and_skips_reddit(settings, monkeypatch):
    page = b"""<html><body><nav>Menu stuff that is long enough to count as text</nav><article>
    <p>The James Webb telescope found a galaxy that formed surprisingly early in the universe.</p>
    <script>evil()</script></article></body></html>"""
    calls = []

    def fake_get(url, **kw):
        calls.append(url)
        return FetchResult(200, url, httpx.Headers({"content-type": "text/html"}), page)

    monkeypatch.setattr(ai, "safe_get", fake_get)
    text = ai.article_text("https://news.example.com/webb", settings, 5000)
    assert "galaxy that formed" in text and "Menu" not in text and "evil" not in text
    assert ai.article_text("https://www.reddit.com/r/x/comments/1/y/", settings, 5000) == ""
    assert calls == ["https://news.example.com/webb"]


def test_admin_ai_test(app, conn, settings, monkeypatch):
    make_user(conn, "admin", admin=True)
    make_user(conn, "a")
    assert login(app, "a").post("/api/admin/ai/test").status_code == 403
    c = login(app, "admin")
    assert c.post("/api/admin/ai/test").json()["ok"] is False  # not configured
    _enable(settings)
    monkeypatch.setattr(ai, "list_models", lambda s: ["llama3.1:8b", "qwen2.5:14b"])
    assert c.post("/api/admin/ai/test").json()["ok"] is True
    settings.llm_model = "mistral"
    r = c.post("/api/admin/ai/test").json()
    assert r["ok"] is False and "qwen2.5:14b" in r["error"]


def test_priority_list_filters_and_sorting(app, conn, settings):
    make_user(conn, "a")
    make_user(conn, "b")
    s1, s2 = make_source(conn, "Homelab"), make_source(conn, "Science")
    i1 = make_item(conn, s1, "Proxmox cluster", age=30)
    i2 = make_item(conn, s1, "ZFS numbers", age=20)
    i3 = make_item(conn, s2, "Octopus dreams", age=10)
    sh = make_short(conn, settings, make_source(conn, "yt", kind="youtube"), "SHORTVID001")
    ca, cb = login(app, "a"), login(app, "b")
    for t, i in (("item", i1), ("item", i2), ("item", i3), ("short", sh)):
        ca.post("/api/react", json={"type": t, "id": i, "value": 1})
    assert ca.post("/api/me/priority", json={"type": "item", "id": i1, "level": "low"}).json() == {"priority": "low"}
    ca.post("/api/me/priority", json={"type": "item", "id": i3, "level": "high"})
    ca.post("/api/me/priority", json={"type": "short", "id": sh, "level": "medium"})
    assert ca.post("/api/me/priority", json={"type": "item", "id": 999, "level": "high"}).status_code == 404

    def get(c, **params):
        d = c.get("/api/me/activity", params=params).json()
        return [(x["type"], x["id"]) for x in d["items"]], d

    by_priority, d = get(ca, kind="liked", sort="priority")
    assert by_priority == [("item", i3), ("short", sh), ("item", i1), ("item", i2)]
    assert {f["title"]: f["count"] for f in d["sources"]} == {"Homelab": 2, "Science": 1, "Chan": 1}
    assert d["items"][0]["priority"] == "high" and d["total"] == 4
    assert get(ca, kind="priority")[0][0] in {("item", i1), ("item", i3), ("short", sh)}
    assert len(get(ca, kind="priority")[0]) == 3
    assert get(ca, kind="liked", type="short")[0] == [("short", sh)]
    assert get(ca, kind="liked", source=s1, sort="oldest")[0] == [("item", i1), ("item", i2)]
    assert get(ca, kind="liked", q="octopus")[0] == [("item", i3)]
    assert get(ca, kind="liked", priority="none")[0] == [("item", i2)]
    assert get(ca, kind="liked", priority="medium")[0] == [("short", sh)]
    assert get(cb, kind="priority")[0] == []  # per user
    # removing a priority, and the reader view shows it
    ca.post("/api/me/priority", json={"type": "item", "id": i1, "level": "none"})
    assert len(get(ca, kind="priority")[0]) == 2
    assert ca.get(f"/api/items/{i3}").json()["priority"] == "high"
    assert ca.get(f"/api/items/{i1}").json()["priority"] is None
