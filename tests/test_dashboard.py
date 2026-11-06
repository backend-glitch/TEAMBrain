import sqlite3

import pytest
from starlette.testclient import TestClient

from server import app as app_module
from server import dashboard
from server import dashboard_users
from server import messages


ORIGIN = "http://127.0.0.1:8000"


@pytest.fixture
def dashboard_client(monkeypatch, tmp_path):
    monkeypatch.setattr(messages, "DB_PATH", tmp_path / "dashboard-test.sqlite3")
    monkeypatch.setenv("TEAMBRAIN_TOKEN_FRONTEND", "frontend-role-token")
    monkeypatch.setenv("TEAMBRAIN_TOKEN_BACKEND", "backend-role-token")
    monkeypatch.setenv("TEAMBRAIN_TOKEN_UIUX", "uiux-role-token")
    monkeypatch.setenv("TEAMBRAIN_DASHBOARD_TOKEN", "dashboard-only-password")
    monkeypatch.setenv("TEAMBRAIN_SESSION_SECRET", "test-session-signing-secret")
    monkeypatch.setenv("TEAMBRAIN_DASHBOARD_PUBLIC", "false")
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
        "roles": [
            {"name": role, "description": "", "color": "#718091", "active": True}
            for role in ("uiux", "frontend", "backend")
        ],
        "proposals": [{
            **thread[0],
            "status": "open",
            "thread": thread,
        }],
        "escalated_proposals": [],
        "recent_messages": [{"id": "sample-message", "body": "Recent activity"}],
        "members": [
            {
                "role": role,
                "ai_name": f"{role} AI",
                "person_name": "",
                "machine_label": "",
                "client_name": "",
                "client_version": "",
                "last_ip": "",
                "first_seen": None,
                "last_seen": None,
                "last_tool": "",
                "request_count": 0,
                "messages_sent": 0,
                "unread_count": 0,
                "unread_messages": [],
                "waiting_on_open_proposal": False,
                "run_mode": "manual",
                "tool_label": "",
            }
            for role in ("uiux", "frontend", "backend")
        ],
    }
    monkeypatch.setattr(dashboard, "dashboard_payload", lambda: payload)

    app = app_module.create_http_app()
    with TestClient(app, base_url=ORIGIN) as client:
        yield client, proposal_id, app


def login(client, password="dashboard-only-password", username="owner"):
    return client.post(
        "/api/login", json={"username": username, "password": password}, headers={"Origin": ORIGIN}
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
    assert response.json() == {"error": "Wrong username or password."}
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


@pytest.mark.parametrize(
    "missing_variable",
    ["TEAMBRAIN_SESSION_SECRET", "TEAMBRAIN_DASHBOARD_TOKEN"],
)
def test_production_startup_requires_session_and_dashboard_secrets(
    monkeypatch, tmp_path, missing_variable
):
    monkeypatch.setattr(messages, "DB_PATH", tmp_path / "production.sqlite3")
    monkeypatch.setenv("TEAMBRAIN_ENV", "production")
    monkeypatch.setenv("TEAMBRAIN_SESSION_SECRET", "configured")
    monkeypatch.setenv("TEAMBRAIN_DASHBOARD_TOKEN", "configured")
    monkeypatch.delenv(missing_variable, raising=False)

    with pytest.raises(RuntimeError, match=missing_variable):
        app_module.create_http_app()


def test_healthz_is_unauthenticated_and_does_not_read_dashboard_data(
    dashboard_client, monkeypatch
):
    client, _, _ = dashboard_client
    monkeypatch.setattr(
        dashboard, "dashboard_payload", lambda: pytest.fail("healthz read dashboard data")
    )

    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_public_dashboard_setting_allows_forwarded_requests_but_keeps_session_and_origin(
    dashboard_client, monkeypatch
):
    client, _, _ = dashboard_client
    remote_headers = {"Cf-Connecting-Ip": "198.51.100.20"}
    assert client.get("/dashboard", headers=remote_headers).status_code == 403
    xff_headers = {"X-Forwarded-For": "198.51.100.20"}
    assert client.get("/dashboard", headers=xff_headers).status_code == 403

    monkeypatch.setenv("TEAMBRAIN_DASHBOARD_PUBLIC", "true")
    assert client.get("/dashboard", headers=remote_headers).status_code == 200
    assert client.get("/dashboard", headers=xff_headers).status_code == 200
    assert client.get("/api/dashboard", headers=remote_headers).status_code == 401

    signed_in = client.post(
        "/api/login",
        json={"password": "dashboard-only-password"},
        headers={**remote_headers, "Origin": ORIGIN},
    )
    assert signed_in.status_code == 200
    assert client.get("/api/dashboard", headers=remote_headers).status_code == 200

    forbidden_action = client.post(
        "/api/tasks/frontend",
        json={"task": "must keep origin check"},
        headers={**remote_headers, "Origin": "https://attacker.example"},
    )
    assert forbidden_action.status_code == 403


def test_production_honors_forwarded_https_and_sets_secure_cookie_and_headers(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(messages, "DB_PATH", tmp_path / "production-http.sqlite3")
    monkeypatch.setenv("TEAMBRAIN_ENV", "production")
    monkeypatch.setenv("TEAMBRAIN_SESSION_SECRET", "test-session-signing-secret")
    monkeypatch.setenv("TEAMBRAIN_DASHBOARD_TOKEN", "dashboard-only-password")
    monkeypatch.setenv("TEAMBRAIN_TOKEN_FRONTEND", "frontend-role-token")
    monkeypatch.setenv("TEAMBRAIN_TOKEN_BACKEND", "backend-role-token")
    monkeypatch.setenv("TEAMBRAIN_TOKEN_UIUX", "uiux-role-token")
    app = app_module.create_http_app()

    with TestClient(app, base_url=ORIGIN) as client:
        response = client.post(
            "/api/login",
            json={"password": "dashboard-only-password"},
            headers={"Origin": "https://127.0.0.1:8000", "X-Forwarded-Proto": "https"},
        )

    assert response.status_code == 200
    assert "Secure" in response.headers["set-cookie"]
    assert response.headers["strict-transport-security"].startswith("max-age=")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    csp = response.headers["content-security-policy"]
    assert "default-src 'none'" in csp
    assert "script-src 'self' 'sha256-" in csp


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
    assert "Activity" in page
    assert "dataset?.recent_messages" in page
    assert "},3000);refresh();" in page
    assert "Contract v${dataset?.contract_version??0}" in page
    assert '"Authorization": `Bearer ${token}`' not in page
    assert 'localStorage.setItem("teambrain-dashboard-theme"' in page
    assert 'localStorage.setItem("teambrain-dashboard-token"' not in page
    assert "@supports(backdrop-filter:blur(16px))" in page
    assert "rgba(255,255,255,.08)" in page
    assert "#0b1026" in page and "#14b8a6" in page and "#c6f432" in page
    assert "https://" not in page and "<script src=" not in page


def test_dashboard_member_profile_is_rendered_as_text_and_edit_requires_session(
    dashboard_client
):
    client, _, _ = dashboard_client
    malicious_name = "<img src=x onerror=alert(1)>"
    dashboard.dashboard_payload()["members"] = [{
        "role": "frontend",
        "ai_name": malicious_name,
        "person_name": "Alex",
        "machine_label": "Workstation",
        "client_name": "Cursor",
        "client_version": "1.0",
        "last_ip": "127.0.0.1",
        "first_seen": None,
        "last_seen": None,
        "last_tool": "set_profile",
        "request_count": 1,
        "messages_sent": 0,
    }]
    assert client.post(
        "/api/members/frontend",
        json={"ai_name": "Nova", "person_name": "Alex", "machine_label": "PC"},
        headers={"Origin": ORIGIN},
    ).status_code == 401
    assert client.post(
        "/api/members/frontend",
        json={"ai_name": "Nova", "person_name": "Alex", "machine_label": "PC"},
        headers={
            "Origin": ORIGIN,
            "Authorization": "Bearer frontend-role-token",
        },
    ).status_code == 401

    assert login(client).status_code == 200
    page = client.get("/dashboard").text
    payload = client.get("/api/dashboard").json()
    assert payload["members"][0]["ai_name"] == malicious_name
    assert "textContent" in page
    assert ".innerHTML" not in page
    assert malicious_name not in page
    assert "navigator.clipboard.writeText(prompt)" in page
    assert "Headless mode is not implemented yet" in page
    assert "dataset?.members" in page
    assert 'id="team-carousel"' in page
    assert 'id="theme-toggle"' in page
    assert 'id="activity-toggle"' in page

    rejected = client.post(
        "/api/members/frontend",
        json={"ai_name": "Nova", "person_name": "Alex", "machine_label": "PC"},
        headers={"Origin": "https://attacker.example"},
    )
    assert rejected.status_code == 403

    accepted = client.post(
        "/api/members/frontend",
        json={
            "ai_name": "Nova",
            "person_name": "Alex",
            "machine_label": "PC",
            "run_mode": "headless",
            "tool_label": "Cursor",
        },
        headers={"Origin": ORIGIN},
    )
    assert accepted.status_code == 200
    assert accepted.json() == {
        "role": "frontend",
        "ai_name": "Nova",
        "person_name": "Alex",
        "machine_label": "PC",
        "run_mode": "headless",
        "tool_label": "Cursor",
    }


def test_dashboard_send_task_creates_owner_proposal_and_requires_session_csrf(
    tmp_path, monkeypatch,
):
    monkeypatch.setattr(messages, "DB_PATH", tmp_path / "send-task.sqlite3")
    monkeypatch.setenv("TEAMBRAIN_TOKEN_FRONTEND", "frontend-role-token")
    monkeypatch.setenv("TEAMBRAIN_TOKEN_BACKEND", "backend-role-token")
    monkeypatch.setenv("TEAMBRAIN_TOKEN_UIUX", "uiux-role-token")
    monkeypatch.setenv("TEAMBRAIN_DASHBOARD_TOKEN", "dashboard-only-password")
    monkeypatch.setenv("TEAMBRAIN_SESSION_SECRET", "test-session-signing-secret")
    dashboard._LOGIN_FAILURES.clear()
    app = app_module.create_http_app()
    client_context = TestClient(app, base_url=ORIGIN)
    client = client_context.__enter__()
    payload = {"task": "Implement the approved pagination spec."}
    try:
        assert client.post(
            "/api/tasks/frontend", json=payload, headers={"Origin": ORIGIN}
        ).status_code == 401
        assert client.post(
            "/api/tasks/frontend",
            json=payload,
            headers={"Origin": ORIGIN, "Authorization": "Bearer frontend-role-token"},
        ).status_code == 401

        assert login(client).status_code == 200
        assert client.post(
            "/api/tasks/frontend",
            json=payload,
            headers={"Origin": "https://attacker.example"},
        ).status_code == 403

        sent = client.post(
            "/api/tasks/frontend", json=payload, headers={"Origin": ORIGIN}
        )
        assert sent.status_code == 201
        response = sent.json()
        thread = messages.get_thread(response["proposal_id"])
        assert len(thread) == 1
        assert thread[0]["from_role"] == "owner"
        assert thread[0]["to_role"] == "frontend"
        assert thread[0]["type"] == "proposal"
        assert thread[0]["body"] == payload["task"]
        dashboard_data = client.get("/api/dashboard").json()
        assert any(item["id"] == response["id"] for item in dashboard_data["recent_messages"])
        assert any(item["id"] == response["proposal_id"] for item in dashboard_data["proposals"])
        frontend = next(member for member in dashboard_data["members"] if member["role"] == "frontend")
        assert frontend["unread_count"] == 1
        assert frontend["waiting_on_open_proposal"] is True
        assert any(item["id"] == response["id"] for item in messages.check_inbox("frontend", peek=True))
    finally:
        client_context.__exit__(None, None, None)


def test_dashboard_member_unread_and_waiting_counts_use_unread_inbox_without_marking(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(messages, "DB_PATH", tmp_path / "unread-dashboard.sqlite3")
    backend_proposal = messages.post_message(
        "owner", "backend", "proposal", "Open backend task", 1,
        allow_owner=True,
    )
    messages.post_message("owner", "backend", "request", "Standalone ping", 1,
                          allow_owner=True)
    frontend_proposal = messages.post_message(
        "owner", "frontend", "proposal", "Resolved frontend task", 1,
        allow_owner=True,
    )
    messages.post_message(
        "backend", "frontend", "accept", "Accepted", 1,
        proposal_id=frontend_proposal["proposal_id"],
    )

    payload = dashboard.dashboard_payload()
    members = {member["role"]: member for member in payload["members"]}
    assert members["backend"]["unread_count"] == 2
    assert members["backend"]["waiting_on_open_proposal"] is True
    assert members["frontend"]["unread_count"] == 2
    assert members["frontend"]["waiting_on_open_proposal"] is False
    assert len(messages.check_inbox("backend", peek=True)) == 2
    assert len(messages.check_inbox("frontend", peek=True)) == 2
    assert messages.get_thread(backend_proposal["proposal_id"])[0]["status"] == "open"


def test_dashboard_handoff_prompt_and_generated_prompt_are_peek_only(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(messages, "DB_PATH", tmp_path / "handoff-dashboard.sqlite3")
    proposal = messages.post_message(
        "backend", "frontend", "proposal", "<script>alert(1)</script>", 4,
        handoff_prompt="Follow the exact handoff.",
    )
    plain = messages.post_message(
        "uiux", "frontend", "request", "Please inspect the issue", 4
    )
    with sqlite3.connect(messages.DB_PATH) as connection:
        connection.execute(
            "UPDATE messages SET created_at = ? WHERE id = ?",
            ("2026-11-06T12:00:00+00:00", proposal["id"]),
        )
        connection.execute(
            "UPDATE messages SET created_at = ? WHERE id = ?",
            ("2026-11-06T11:00:00+00:00", plain["id"]),
        )

    payload = dashboard.dashboard_payload()
    frontend = next(member for member in payload["members"] if member["role"] == "frontend")
    by_id = {message["id"]: message for message in frontend["unread_messages"]}
    assert by_id[proposal["id"]]["handoff_prompt"] == "Follow the exact handoff."
    assert by_id[plain["id"]]["handoff_prompt"] is None
    assert [message["id"] for message in frontend["unread_messages"]] == [proposal["id"], plain["id"]]
    with sqlite3.connect(messages.DB_PATH) as connection:
        read_values = connection.execute(
            'SELECT id, "read" FROM messages ORDER BY created_at DESC, id DESC'
        ).fetchall()
    assert all(value == 0 for _, value in read_values)

    page = dashboard.DASHBOARD_HTML
    assert 'message.handoff_prompt||`You are the ${member.role}. Use only the TeamBrain MCP tools. ${message.from_role} says: ${message.body}. Read thread ${message.proposal_id||"(no proposal_id)"}, do what it asks, reply with objection or accept using proposal_id, then mark_read.`' in page
    assert 'el("p","handoff-prompt",prompt)' in page
    assert 'link.type="button"' in page
    assert 'navigator.clipboard.writeText(prompt)' in page
    assert ".innerHTML" not in page
    assert "textContent" in page


def test_dashboard_session_does_not_authenticate_mcp_route(dashboard_client):
    client, _, _ = dashboard_client
    assert login(client).status_code == 200

    response = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
    )

    assert response.status_code == 401


def test_dashboard_api_includes_standalone_messages_newest_first(tmp_path, monkeypatch):
    monkeypatch.setattr(messages, "DB_PATH", tmp_path / "dashboard.sqlite3")
    monkeypatch.setenv("TEAMBRAIN_TOKEN_FRONTEND", "frontend-role-token")
    monkeypatch.setenv("TEAMBRAIN_TOKEN_BACKEND", "backend-role-token")
    monkeypatch.setenv("TEAMBRAIN_TOKEN_UIUX", "uiux-role-token")
    monkeypatch.setenv("TEAMBRAIN_DASHBOARD_TOKEN", "dashboard-only-password")
    monkeypatch.setenv("TEAMBRAIN_SESSION_SECRET", "test-session-signing-secret")

    older = messages.post_message(
        "backend", "frontend", "request", "Standalone request", 1
    )
    newer = messages.post_message(
        "uiux", "frontend", "accept", "Standalone accept", 1
    )
    with sqlite3.connect(messages.DB_PATH) as connection:
        connection.execute(
            "UPDATE messages SET created_at = ? WHERE id = ?",
            ("2026-11-05T10:00:00+00:00", older["id"]),
        )
        connection.execute(
            "UPDATE messages SET created_at = ? WHERE id = ?",
            ("2026-11-05T11:00:00+00:00", newer["id"]),
        )

    app = app_module.create_http_app()
    with TestClient(app, base_url=ORIGIN) as client:
        assert login(client).status_code == 200
        response = client.get("/api/dashboard")

    assert response.status_code == 200
    payload = response.json()
    recent = payload["recent_messages"]
    assert [item["id"] for item in recent] == [newer["id"], older["id"]]
    assert recent[0] == {
        "id": newer["id"],
        "from_role": "uiux",
        "to_role": "frontend",
        "type": "accept",
        "body": "Standalone accept",
        "contract_version": 1,
        "handoff_prompt": None,
        "created_at": "2026-11-05T11:00:00+00:00",
    }
    assert payload["proposals"] == []


def test_add_role_requires_dashboard_session_and_same_origin(dashboard_client):
    client, _, _ = dashboard_client
    payload = {"name": "qa2", "description": "Quality checks", "color": "#95d7a5"}
    assert client.post(
        "/api/roles", json=payload, headers={"Origin": ORIGIN}
    ).status_code == 401
    assert client.post(
        "/api/roles", json=payload,
        headers={"Origin": ORIGIN, "Authorization": "Bearer frontend-role-token"},
    ).status_code == 401

    assert login(client).status_code == 200
    assert client.post(
        "/api/roles", json=payload, headers={"Origin": "https://attacker.example"}
    ).status_code == 403
    response = client.post(
        "/api/roles", json=payload, headers={"Origin": ORIGIN}
    )

    assert response.status_code == 201
    role = response.json()
    assert role["name"] == "qa2"
    assert role["token_env_var"] == "TEAMBRAIN_TOKEN_QA2"
    assert "manually" in role["token_setup"]
    assert set(role) == {
        "name", "description", "color", "active", "token_env_var",
        "can_write_contract", "token_setup",
    }


def test_dashboard_add_role_page_uses_dynamic_roles_and_safe_text(dashboard_client):
    client, _, _ = dashboard_client
    page = client.get("/dashboard").text

    assert 'id="add-role-form"' in page
    assert "dataset?.roles" in page
    assert "Set ${data.token_env_var}" in page
    assert "The server never generates or stores tokens." in page
    assert ".innerHTML" not in page


def test_dashboard_human_decision_requires_session_csrf_and_resolves_escalated(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(messages, "DB_PATH", tmp_path / "dashboard-decision.sqlite3")
    monkeypatch.setenv("TEAMBRAIN_TOKEN_FRONTEND", "frontend-role-token")
    monkeypatch.setenv("TEAMBRAIN_TOKEN_BACKEND", "backend-role-token")
    monkeypatch.setenv("TEAMBRAIN_TOKEN_UIUX", "uiux-role-token")
    monkeypatch.setenv("TEAMBRAIN_DASHBOARD_TOKEN", "dashboard-only-password")
    monkeypatch.setenv("TEAMBRAIN_SESSION_SECRET", "test-session-signing-secret")
    dashboard._LOGIN_FAILURES.clear()
    app = app_module.create_http_app()
    with TestClient(app, base_url=ORIGIN) as client:
        proposal = messages.post_message("frontend", "backend", "proposal", "Set cursor paging", 1)
        for _ in range(3):
            messages.post_message(
                "backend", "frontend", "objection", "Needs cursor semantics", 1,
                proposal_id=proposal["proposal_id"],
            )
        path = f"/api/proposals/{proposal['proposal_id']}/decision"
        payload = {"decision": "reject", "note": "Define cursor semantics first."}
        assert client.post(path, json=payload, headers={"Origin": ORIGIN}).status_code == 401
        assert login(client).status_code == 200
        assert client.post(
            path, json=payload, headers={"Origin": "https://attacker.example"}
        ).status_code == 403
        response = client.post(path, json=payload, headers={"Origin": ORIGIN})

    assert response.status_code == 200
    assert response.json()["status"] == "rejected"
    assert response.json()["note"] == payload["note"]
    assert messages.get_thread(proposal["proposal_id"])[0]["status"] == "rejected"


def test_member_dashboard_is_scoped_to_linked_role_and_redacts_private_metadata(
    dashboard_client
):
    client, _, _ = dashboard_client
    dashboard_users.create_user(
        "frontend-user", "a long member password", "member", "frontend"
    )

    response = client.post(
        "/api/login",
        json={"username": "frontend-user", "password": "a long member password"},
        headers={"Origin": ORIGIN},
    )
    assert response.status_code == 200
    payload = client.get("/api/dashboard").json()

    assert payload["viewer"]["role_scope"] == "member"
    assert payload["viewer"]["linked_role"] == "frontend"
    assert len(payload["members"]) == 1
    assert payload["members"][0]["role"] == "frontend"
    assert "last_ip" not in payload["members"][0]
    assert "machine_label" not in payload["members"][0]
    assert payload["proposals"]
    assert "recent_messages" in payload
    assert "dashboard_users" not in payload


def test_owner_dashboard_retains_all_role_metadata(dashboard_client):
    client, _, _ = dashboard_client
    assert login(client).status_code == 200
    payload = client.get("/api/dashboard").json()

    assert payload["viewer"]["role_scope"] == "owner"
    assert {member["role"] for member in payload["members"]} == {
        "uiux", "frontend", "backend"
    }
    assert all("last_ip" in member and "machine_label" in member for member in payload["members"])
    assert payload["fallback_owner_enabled"] is True


def test_member_is_denied_every_owner_only_action_and_other_role_changes(
    dashboard_client
):
    client, proposal_id, _ = dashboard_client
    dashboard_users.create_user(
        "frontend-user", "a long member password", "member", "frontend"
    )
    assert client.post(
        "/api/login",
        json={"username": "frontend-user", "password": "a long member password"},
        headers={"Origin": ORIGIN},
    ).status_code == 200
    origin = {"Origin": ORIGIN}

    assert client.get("/api/users").status_code == 403
    assert client.post("/api/users", json={}, headers=origin).status_code == 403
    assert client.post(
        "/api/users/fallback", json={"enabled": False}, headers=origin
    ).status_code == 403
    assert client.post(
        "/api/roles", json={"name": "newrole", "color": "#112233"}, headers=origin
    ).status_code == 403
    assert client.post(
        "/api/roles/backend/active", json={"active": False}, headers=origin
    ).status_code == 403
    assert client.post(
        f"/api/proposals/{proposal_id}/decision",
        json={"decision": "reject"},
        headers=origin,
    ).status_code == 403
    assert client.post(
        "/api/tasks/backend", json={"task": "other role"}, headers=origin
    ).status_code == 403
    assert client.post(
        "/api/members/backend",
        json={"ai_name": "Changed", "person_name": "", "machine_label": ""},
        headers=origin,
    ).status_code == 403

    own_task = client.post(
        "/api/tasks/frontend", json={"task": "my role task"}, headers=origin
    )
    assert own_task.status_code == 201
    own_profile = client.post(
        "/api/members/frontend",
        json={"ai_name": "Front AI", "person_name": "", "machine_label": ""},
        headers=origin,
    )
    assert own_profile.status_code == 200


def test_owner_can_create_disable_reset_users_and_disable_fallback(dashboard_client):
    client, _, _ = dashboard_client
    assert login(client).status_code == 200
    fallback_cookie = client.cookies.get(dashboard.SESSION_COOKIE)

    assert client.post(
        "/api/users",
        json={"username": "missing-csrf", "password": "long enough password", "role_scope": "owner"},
    ).status_code == 403
    created_owner = client.post(
        "/api/users",
        json={
            "username": "backup-owner",
            "password": "a secure owner password",
            "role_scope": "owner",
            "linked_role": None,
        },
        headers={"Origin": ORIGIN},
    )
    assert created_owner.status_code == 201
    assert "password" not in created_owner.json()
    assert "password_hash" not in created_owner.json()
    assert "password_hash" not in client.get("/api/users").text

    created_member = client.post(
        "/api/users",
        json={
            "username": "front-user",
            "password": "a secure member password",
            "role_scope": "member",
            "linked_role": "frontend",
        },
        headers={"Origin": ORIGIN},
    )
    assert created_member.status_code == 201

    reset = client.post(
        "/api/users/front-user/password",
        json={"password": "a changed member password"},
        headers={"Origin": ORIGIN},
    )
    assert reset.status_code == 200
    assert "password" not in reset.text
    assert dashboard_users.authenticate_user("front-user", "a secure member password") is None
    assert dashboard_users.authenticate_user("front-user", "a changed member password") is not None

    client.cookies.clear()
    assert login(client, "a changed member password", "front-user").status_code == 200
    member_cookie = client.cookies.get(dashboard.SESSION_COOKIE)
    client.cookies.clear()
    client.cookies.set(dashboard.SESSION_COOKIE, fallback_cookie)

    disabled = client.post(
        "/api/users/front-user/disabled",
        json={"disabled": True},
        headers={"Origin": ORIGIN},
    )
    assert disabled.status_code == 200
    assert dashboard_users.authenticate_user("front-user", "a changed member password") is None
    assert client.get("/api/users").json()["users"][-1]["disabled"] is True

    client.cookies.clear()
    client.cookies.set(dashboard.SESSION_COOKIE, member_cookie)
    assert client.get("/api/dashboard").status_code == 401
    client.cookies.clear()
    client.cookies.set(dashboard.SESSION_COOKIE, fallback_cookie)

    fallback = client.post(
        "/api/users/fallback",
        json={"enabled": False},
        headers={"Origin": ORIGIN},
    )
    assert fallback.status_code == 200
    assert client.get("/api/dashboard").status_code == 401

    assert login(client).status_code == 401
    assert login(client, "a secure owner password", "backup-owner").status_code == 200
