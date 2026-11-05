import asyncio

from server import app as app_module
from server.http_auth import BearerRoleMiddleware, configured_tokens, current_role


def invoke_middleware(middleware, authorization=None):
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/mcp",
        "raw_path": b"/mcp",
        "query_string": b"",
        "headers": (
            [(b"authorization", authorization.encode("latin-1"))]
            if authorization is not None
            else []
        ),
        "client": ("127.0.0.1", 12345),
        "server": ("127.0.0.1", 8000),
    }
    events = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        events.append(message)

    asyncio.run(middleware(scope, receive, send))
    return events


def test_bearer_middleware_rejects_missing_and_wrong_tokens():
    async def app(scope, receive, send):
        raise AssertionError("unauthorized request reached the application")

    middleware = BearerRoleMiddleware(app, {"frontend": "frontend-secret"})

    for authorization in (None, "Bearer wrong-secret"):
        events = invoke_middleware(middleware, authorization)
        assert events[0]["status"] == 401


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

    def fake_check_inbox(**kwargs):
        requested.update(kwargs)
        return []

    monkeypatch.setattr(app_module, "check_inbox", fake_check_inbox)
    role_token = current_role.set("frontend")
    try:
        app_module.check_inbox_tool(to_role="backend", peek=True)
    finally:
        current_role.reset(role_token)

    assert requested == {"to_role": "frontend", "peek": True}
