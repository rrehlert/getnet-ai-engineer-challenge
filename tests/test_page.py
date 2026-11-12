"""The demo client: the static page at `/`, its assets, `/dev/users`, and the textContent-only rule."""

import re
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.auth import OPERATORS, AuthSettings
from app.main import STATIC_DIR, create_app
from app.support import load_merchants

SECRET = "test-secret-at-least-32-bytes-long"
NOW = datetime(2026, 11, 11, 12, 0, tzinfo=UTC)
STATIC_FILES = sorted(p.name for p in STATIC_DIR.iterdir() if p.is_file())
SCRIPTS = sorted(p.name for p in STATIC_DIR.glob("*.js"))


def make_app(demo_login=True):
    """No graph is built for these routes; Judges off (no real LLM calls)."""
    return create_app(auth=AuthSettings(secret=SECRET, demo_login=demo_login, clock=lambda: NOW), judge_enabled=False)


def test_root_serves_the_page():
    response = TestClient(make_app()).get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "<title>Merchant Support (demo)</title>" in response.text
    assert 'src="/static/app.js"' in response.text
    # View scripts load before app.js, whose ROLE_VIEWS names their views.
    assert response.text.index('src="/static/merchant.js"') < response.text.index('src="/static/app.js"')
    # The Operator view registers itself in app.js's ROLE_VIEWS, so it must load after it.
    assert response.text.index('src="/static/app.js"') < response.text.index('src="/static/operator.js"')
    # The events panel registers itself in operator.js's OPERATOR_PANELS.
    assert response.text.index('src="/static/operator.js"') < response.text.index('src="/static/events.js"')
    assert 'href="/static/style.css"' in response.text
    # Same-origin scripts only: no inline script, no CDN.
    assert "script-src" not in response.headers["content-security-policy"]
    assert "default-src 'self'" in response.headers["content-security-policy"]


CONTENT_TYPES = {".js": "javascript", ".css": "text/css", ".html": "text/html"}


@pytest.mark.parametrize("name", STATIC_FILES)
def test_assets_are_served(name):
    response = TestClient(make_app()).get(f"/static/{name}")

    assert response.status_code == 200
    assert CONTENT_TYPES[Path(name).suffix] in response.headers["content-type"]
    assert response.content == (STATIC_DIR / name).read_bytes()


def test_every_script_is_loaded_by_the_page():
    page = (STATIC_DIR / "index.html").read_text(encoding="utf-8")

    assert {"app.js", "merchant.js", "operator.js", "events.js"} <= set(SCRIPTS)
    for name in SCRIPTS:
        assert f'<script src="/static/{name}" defer></script>' in page, name


def test_page_works_without_demo_login():
    client = TestClient(make_app(demo_login=False))

    assert client.get("/").status_code == 200
    assert client.get("/static/app.js").status_code == 200


def test_page_loads_nothing_from_other_origins():
    for name in STATIC_FILES:
        text = (STATIC_DIR / name).read_text(encoding="utf-8")
        assert not re.search(r"""(src|href)\s*=\s*["']?(https?:)?//""", text), name
        assert "@import" not in text, name


def test_dev_users_is_404_when_demo_login_is_off():
    client = TestClient(make_app(demo_login=False))

    response = client.get("/dev/users")

    assert response.status_code == 404
    assert response.json() == client.get("/no-such-path").json()


def test_dev_users_lists_fixture_merchants_and_operators_with_roles():
    response = TestClient(make_app()).get("/dev/users")

    assert response.status_code == 200
    users = {u["id"]: u["role"] for u in response.json()["users"]}
    merchants = set(load_merchants(NOW.date()))
    assert merchants  # the fixture is not empty
    assert users == {
        **{m: "merchant" for m in merchants},
        **{o: "operator" for o in OPERATORS},
    }


def test_every_dev_user_logs_in_with_the_listed_role():
    client = TestClient(make_app())

    for user in client.get("/dev/users").json()["users"]:
        token = client.post("/dev/login", json={"user_id": user["id"]}).json()["access_token"]
        me = client.get("/me", headers={"Authorization": f"Bearer {token}"}).json()
        assert (me["sub"], me["role"]) == (user["id"], user["role"])


# ---------- untrusted text only through textContent ----------

# `x.innerHTML = "static";` (a single plain string literal, nothing concatenated) is the only allowed use.
STATIC_ASSIGNMENT = re.compile(r"""\.innerHTML\s*=\s*(?:"[^"\\\n]*"|'[^'\\\n]*')\s*;""")
FORBIDDEN = re.compile(r"insertAdjacentHTML|outerHTML|document\.write|createContextualFragment|DOMParser")


def html_sink_violations(source: str) -> list[str]:
    """Lines that write HTML from anything other than a static string literal."""
    bad = []
    for number, line in enumerate(source.splitlines(), 1):
        code = line.split("//", 1)[0] if line.lstrip().startswith("//") else line
        for match in re.finditer(r"innerHTML", code):
            if not STATIC_ASSIGNMENT.match(code, match.start() - 1):
                bad.append(f"{number}: {line.strip()}")
        if FORBIDDEN.search(code):
            bad.append(f"{number}: {line.strip()}")
    return bad


@pytest.mark.parametrize("name", SCRIPTS)
def test_scripts_write_no_html_from_dynamic_values(name):
    """Every app/static/*.js, so each new view script is covered without touching this test."""
    assert html_sink_violations((STATIC_DIR / name).read_text(encoding="utf-8")) == []


@pytest.mark.parametrize("line", [
    "node.innerHTML = text;",
    "node.innerHTML = '<b>' + text + '</b>';",
    "node.innerHTML += 'x';",
    "node.innerHTML = `<b>${text}</b>`;",
    "node.innerHTML = 'a' + b;",
    "node.innerHTML=x",
    "node.insertAdjacentHTML('beforeend', '<b>x</b>');",
    "node.outerHTML = '<b>x</b>';",
    "document.write(text);",
])
def test_the_check_catches_dynamic_html(line):
    assert html_sink_violations(line) != []


@pytest.mark.parametrize("line", [
    "node.innerHTML = '';",
    'node.innerHTML = "<hr>";',
    "node.textContent = text;",
    "// never use innerHTML with user text",
])
def test_the_check_allows_static_strings_and_text(line):
    assert html_sink_violations(line) == []
