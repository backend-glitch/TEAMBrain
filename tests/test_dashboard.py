import pytest
from starlette.testclient import TestClient

from server import app as app_module
from server import dashboard


ORIGIN = "http://127.0.0.1:8000"


@pytest.fixture
def dashboard_client(monkeypatch):
    monkeypatch.setenv("TEAMBRAIN_TOKEN_FRONTEND", "frontend-role-token")
    monkeypatch.setenv("TEAMBRAIN_TOKEN_BACKEND", "backend-role-token")
    monkeypatch.setenv("TEAMBRAIN_TOKEN_UIUX", "uiux-role-token")
    monkeypatch.setenv("TEAMBRAIN_DASHBOARD_TOKEN", "dashboard-only-password")
    monkeypatch.setenv("TEAMBRAIN_SESSION_SECRET", "test-session-signing-secret")
    dashboard._LOGIN_FAILURES.clear()

    proposal_id = "sample-proposal"
    thread = [{
        "id": "sample-proposal",
        "from_role": "backend",
        "to_role": "frontend",
        "type": "proposal",
        "body": "<script>alert('x')</script>",
        "contract_version": 1,
        "created_at": "2026-11-05T10:00:00+00:00",
    }]
    payload = {
        "contract_version": 1,
        "proposals": [{
            **thread[0],
            "status": "open",
            "thread": thread,
        }],
        "escalated_proposals": [],
    }
    monkeypatch.setattr(dashboard, "dashboard_payload", lambda: payload)

    app = app_module.create_http_app()
    with TestClient(app, base_url=ORIGIN) as client:
        yield client, proposal_id, app


def login(client, password="dashboard-only-password"):
    return client.post(
        "/api/login", json={"password": password}, headers={"Origin": ORIGIN}
    )


def test_dashboard_without_cookie_shows_login_and_api_returns_401(dashboard_client):
    client, _, _ = dashboard_client

    page = client.get("/dashboard")
    assert page.status_code == 200
    assert 'type="password"' in page.text
    assert "Sign in" in page.text
    assert client.get("/api/dashboard").status_code == 401


def test_wrong_password_fails_with_friendly_error(dashboard_client):
    client, _, _ = dashboard_client

    response = login(client, "not-the-password")

    assert response.status_code == 401
    assert response.json() == {"error": "Wrong password."}
    assert "set-cookie" not in response.headers


def test_correct_password_sets_signed_session_cookie(dashboard_client):
    client, _, _ = dashboard_client

    response = login(client)

    assert response.status_code == 200
    cookie = response.headers["set-cookie"]
    assert "teambrain_session=" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=strict" in cookie
    assert "Max-Age=604800" in cookie
    assert "expires=" in cookie.lower()
    assert "Secure" not in cookie
    assert client.get("/api/dashboard").status_code == 200


def test_https_login_sets_secure_cookie(dashboard_client):
    client, _, _ = dashboard_client

    response = client.post(
        "https://127.0.0.1:8000/api/login",
        json={"password": "dashboard-only-password"},
        headers={"Origin": "https://127.0.0.1:8000"},
    )

    assert response.status_code == 200
    assert "Secure" in response.headers["set-cookie"]


def test_session_cookie_survives_simulated_reload(dashboard_client):
    client, _, _ = dashboard_client
    assert login(client).status_code == 200
    session_cookie = client.cookies.get(dashboard.SESSION_COOKIE)
    client.cookies.clear()
    client.cookies.set(dashboard.SESSION_COOKIE, session_cookie)

    response = client.get("/dashboard")
    assert response.status_code == 200
    response = client.get("/api/dashboard")
    assert response.status_code == 200


def test_logout_clears_cookie_and_invalidates_client_session(dashboard_client):
    client, _, _ = dashboard_client
    assert login(client).status_code == 200
    assert client.get("/api/dashboard").status_code == 200

    response = client.post("/api/logout", headers={"Origin": ORIGIN})

    assert response.status_code == 200
    assert "Max-Age=0" in response.headers["set-cookie"]
    assert client.get("/api/dashboard").status_code == 401


def test_role_token_does_not_authenticate_dashboard(dashboard_client):
    client, _, _ = dashboard_client

    response = client.get(
        "/api/dashboard", headers={"Authorization": "Bearer frontend-role-token"}
    )

    assert response.status_code == 401


def test_login_rate_limit_allows_five_failures_then_returns_429(dashboard_client):
    client, _, _ = dashboard_client

    statuses = [login(client, "wrong-password").status_code for _ in range(6)]

    assert statuses == [401, 401, 401, 401, 401, 429]


def test_dashboard_post_requires_same_origin(dashboard_client):
    client, _, _ = dashboard_client

    response = client.post("/api/login", json={"password": "dashboard-only-password"})

    assert response.status_code == 403


def test_script_message_is_data_and_page_uses_text_content(dashboard_client):
    client, proposal_id, _ = dashboard_client
    assert login(client).status_code == 200

    payload = client.get("/api/dashboard").json()
    proposal = next(item for item in payload["proposals"] if item["id"] == proposal_id)
    page = client.get("/dashboard").text

    assert proposal["thread"][0]["body"] == "<script>alert('x')</script>"
    assert "textContent" in page
    assert ".innerHTML" not in page
    assert "<script>alert('x')</script>" not in page
    assert 'fetch("/api/dashboard"' in page
    assert '"Authorization": `Bearer ${token}`' not in page
    assert "localStorage" not in page


def test_dashboard_session_does_not_authenticate_mcp_route(dashboard_client):
    client, _, _ = dashboard_client
    assert login(client).status_code == 200

    response = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
    )

    assert response.status_code == 401
