import json
import sqlite3

from server import app as app_module
from server.http_auth import BearerRoleMiddleware, configured_tokens, current_role
from server import messages


def invoke_middleware(
    middleware, authorization=None, path="/mcp", forwarded_headers=None,
    body: bytes = b"", client=("127.0.0.1", 12345),
):
    headers = []
    if authorization is not None:
        headers.append((b"authorization", authorization.encode("latin-1")))
    for name, value in (forwarded_headers or {}).items():
        headers.append((name.lower().encode("latin-1"), value.encode("latin-1")))
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("ascii"),
        "query_string": b"",
        "headers": headers,
        "client": client,
        "server": ("127.0.0.1", 8000),
    }
    events = []

    delivered = False

    async def receive():
        nonlocal delivered
        if delivered:
            return {"type": "http.disconnect"}
        delivered = True
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message):
        events.append(message)

    coroutine = middleware(scope, receive, send)
    try:
        coroutine.send(None)
    except StopIteration:
        pass
    else:
        raise AssertionError("test middleware unexpectedly suspended")
    return events


def test_bearer_middleware_rejects_missing_and_wrong_tokens():
    async def app(scope, receive, send):
        raise AssertionError("unauthorized request reached the application")

    middleware = BearerRoleMiddleware(app, {"frontend": "frontend-secret"})

    for authorization in (None, "Bearer wrong-secret"):
        events = invoke_middleware(middleware, authorization)
        assert events[0]["status"] == 401


def test_forwarded_headers_are_rejected_for_dashboard_and_api_but_not_mcp():
    reached_paths = []

    async def app(scope, receive, send):
        reached_paths.append(scope["path"])
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    middleware = BearerRoleMiddleware(app, {"backend": "backend-secret"})

    for path, forwarded in (
        ("/dashboard", {"Cf-Connecting-Ip": "203.0.113.10"}),
        ("/api/dashboard", {"X-Forwarded-For": "203.0.113.10"}),
        ("/api/login", {"cf-connecting-ip": ""}),
        ("/api/tasks/frontend", {"Cf-Connecting-Ip": "203.0.113.11"}),
    ):
        events = invoke_middleware(
            middleware, path=path, forwarded_headers=forwarded
        )
        assert events[0]["status"] == 403

    events = invoke_middleware(
        middleware,
        authorization="Bearer backend-secret",
        path="/mcp",
        forwarded_headers={"X-Forwarded-For": "203.0.113.10"},
    )

    assert events[0]["status"] == 200
    assert reached_paths == ["/mcp"]


def test_configured_tokens_map_environment_variables_to_roles(monkeypatch):
    monkeypatch.setenv("TEAMBRAIN_TOKEN_UIUX", "uiux-secret")
    monkeypatch.setenv("TEAMBRAIN_TOKEN_FRONTEND", "frontend-secret")
    monkeypatch.setenv("TEAMBRAIN_TOKEN_BACKEND", "backend-secret")

    assert configured_tokens() == {
        "uiux": "uiux-secret",
        "frontend": "frontend-secret",
        "backend": "backend-secret",
    }


def test_bearer_middleware_sets_role_for_valid_token():
    seen_roles = []

    async def app(scope, receive, send):
        seen_roles.append(current_role.get())
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    middleware = BearerRoleMiddleware(app, {"backend": "backend-secret"})

    events = invoke_middleware(middleware, "Bearer backend-secret")

    assert events[0]["status"] == 200
    assert seen_roles == ["backend"]
    assert current_role.get() is None


def test_authenticated_mcp_request_updates_member_and_extracts_client_info(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(messages, "DB_PATH", tmp_path / "members.sqlite3")
    initialize_body = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"clientInfo": {"name": "Cursor", "version": "2.1"}},
        }
    ).encode()
    tool_call_body = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 7,
            "method": "tools/call",
            "params": {"name": "post_message", "arguments": {"body": "secret body"}},
        }
    ).encode()
    seen = []

    async def app(scope, receive, send):
        seen.append(await receive())
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    middleware = BearerRoleMiddleware(app, {"frontend": "frontend-secret"})
    initialize_events = invoke_middleware(
        middleware,
        authorization="Bearer frontend-secret",
        body=initialize_body,
        client=("127.0.0.8", 12345),
    )
    events = invoke_middleware(
        middleware,
        authorization="Bearer frontend-secret",
        body=tool_call_body,
        forwarded_headers={"X-Forwarded-For": "198.51.100.1, 10.0.0.2"},
        client=("127.0.0.8", 12345),
    )

    assert initialize_events[0]["status"] == 200
    assert events[0]["status"] == 200
    assert [event["body"] for event in seen] == [initialize_body, tool_call_body]
    with sqlite3.connect(messages.DB_PATH) as connection:
        row = connection.execute(
            "SELECT role, client_name, client_version, last_ip, last_seen, first_seen, "
            "last_tool, request_count "
            "FROM members WHERE role = 'frontend'"
        ).fetchone()
        columns = {item[1] for item in connection.execute("PRAGMA table_info(members)")}
    assert row[0] == "frontend"
    assert row[1:3] == ("Cursor", "2.1")
    assert row[3] == "198.51.100.1"
    assert row[4] and row[5]
    assert row[4] >= row[5]
    assert row[6:] == ("post_message", 2)
    assert "body" not in columns
    assert "token" not in columns


def test_cf_connecting_ip_has_priority_over_forwarded_and_socket_addresses(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(messages, "DB_PATH", tmp_path / "members.sqlite3")

    async def app(scope, receive, send):
        await receive()
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    middleware = BearerRoleMiddleware(app, {"backend": "backend-secret"})
    invoke_middleware(
        middleware,
        authorization="Bearer backend-secret",
        forwarded_headers={
            "Cf-Connecting-Ip": "203.0.113.9",
            "X-Forwarded-For": "198.51.100.3, 10.0.0.2",
        },
        client=("127.0.0.8", 12345),
    )

    with sqlite3.connect(messages.DB_PATH) as connection:
        last_ip = connection.execute(
            "SELECT last_ip FROM members WHERE role = 'backend'"
        ).fetchone()[0]
    assert last_ip == "203.0.113.9"


def test_post_message_uses_authenticated_role_instead_of_client_from_role(monkeypatch):
    saved = {}

    def fake_post_message(**kwargs):
        saved.update(kwargs)
        return {"id": "message-id"}

    monkeypatch.setattr(app_module, "post_message", fake_post_message)
    role_token = current_role.set("frontend")
    try:
        app_module.post_message_tool(
            from_role="backend",
            to_role="backend",
            type="request",
            body="Hello",
            contract_version=1,
        )
    finally:
        current_role.reset(role_token)

    assert saved["from_role"] == "frontend"
    assert saved["to_role"] == "backend"


def test_check_inbox_uses_authenticated_role_instead_of_client_role(monkeypatch):
    requested = {}
    monkeypatch.setattr(
        app_module,
        "get_team_status",
        lambda: {
            "roles": [
                {"role": "uiux", "current_status": None},
                {"role": "frontend", "current_status": None},
                {"role": "backend", "current_status": None},
            ]
        },
    )

    def fake_check_inbox(**kwargs):
        requested.update(kwargs)
        return []

    monkeypatch.setattr(app_module, "check_inbox", fake_check_inbox)
    role_token = current_role.set("frontend")
    try:
        result = app_module.check_inbox_tool(to_role="backend", peek=True)
    finally:
        current_role.reset(role_token)

    assert requested == {"to_role": "frontend", "peek": True}
    assert result == {
        "messages": [],
        "team_status_summary": [
            {
                "role": "uiux",
                "state": None,
                "summary": "No status posted",
                "task": None,
            },
            {
                "role": "backend",
                "state": None,
                "summary": "No status posted",
                "task": None,
            },
        ],
    }


def test_mark_read_tool_only_marks_messages_for_authenticated_role(tmp_path, monkeypatch):
    from server import messages

    monkeypatch.setattr(messages, "DB_PATH", tmp_path / "messages.sqlite3")
    frontend_message = messages.post_message(
        "backend", "frontend", "request", "For frontend", 1
    )
    backend_message = messages.post_message(
        "frontend", "backend", "request", "For backend", 1
    )
    role_token = current_role.set("frontend")
    try:
        result = app_module.mark_read_tool(
            [frontend_message["id"], backend_message["id"]]
        )
    finally:
        current_role.reset(role_token)

    assert result == {"marked_read": [frontend_message["id"]]}
    assert messages.check_inbox("backend", peek=True)[0]["id"] == backend_message["id"]


def test_mark_read_tool_requires_an_authenticated_role():
    try:
        app_module.mark_read_tool(["message-id"])
    except PermissionError as error:
        assert str(error) == "mark_read requires an authenticated role"
    else:
        raise AssertionError("mark_read must reject calls without an authenticated role")
