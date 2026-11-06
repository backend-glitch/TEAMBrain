"""Bearer token authentication for TeamBrain's HTTP transport."""

import hmac
import json
import os
from contextvars import ContextVar
from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send
from server.deployment import dashboard_public
from server.storage import connect


current_role: ContextVar[str | None] = ContextVar("teambrain_current_role", default=None)

MAX_METADATA_BODY_SIZE = 256 * 1024


def _mcp_request_metadata(body: bytes) -> tuple[str | None, str | None, str | None]:
    """Extract only protocol identity and tool name metadata from JSON-RPC."""
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None, None, None
    entries = payload if isinstance(payload, list) else [payload]
    client_name = client_version = last_tool = None
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        params = entry.get("params")
        if not isinstance(params, dict):
            continue
        if entry.get("method") == "initialize":
            client_info = params.get("clientInfo")
            if isinstance(client_info, dict):
                name, version = client_info.get("name"), client_info.get("version")
                client_name = name[:100] if isinstance(name, str) else client_name
                client_version = version[:100] if isinstance(version, str) else client_version
        elif entry.get("method") == "tools/call":
            name = params.get("name")
            if isinstance(name, str) and name:
                last_tool = name[:100]
    return client_name, client_version, last_tool


def configured_tokens() -> dict[str, str]:
    """Load tokens for active database roles, omitting unset values."""
    from server.database import create_tables
    with connect() as connection:
        create_tables(connection)
        role_environment = connection.execute(
            "SELECT name, token_env_var FROM roles WHERE active = 1 ORDER BY rowid"
        ).fetchall()
    return {
        role: token
        for role, variable in role_environment
        if (token := os.environ.get(variable))
    }


class BearerRoleMiddleware:
    """Authenticate dashboard and MCP routes with separate bearer tokens."""

    DASHBOARD_PATHS = {
        "/dashboard",
        "/api/dashboard",
        "/api/login",
        "/api/logout",
        "/api/roles",
        "/api/proposals",
        "/api/users",
    }

    def __init__(
        self,
        app: ASGIApp,
        tokens: dict[str, str] | None = None,
        dashboard_token: str | None = None,
    ):
        self.app = app
        self.tokens = tokens
        self.dashboard_token = dashboard_token
        if dashboard_token and tokens and dashboard_token in tokens.values():
            raise ValueError("TEAMBRAIN_DASHBOARD_TOKEN must be distinct from role tokens")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        is_dashboard_api = path == "/api" or path.startswith("/api/")
        if path == "/dashboard" or is_dashboard_api:
            forwarded_headers = {key.lower() for key, _ in scope["headers"]}
            if (
                not dashboard_public()
                and (
                    b"cf-connecting-ip" in forwarded_headers
                    or b"x-forwarded-for" in forwarded_headers
                )
            ):
                await PlainTextResponse("Forbidden", status_code=403)(
                    scope, receive, send
                )
                return

        if path == "/healthz":
            await self.app(scope, receive, send)
            return

        if (
            path in self.DASHBOARD_PATHS
            or path.startswith("/api/members/")
            or path.startswith("/api/tasks/")
            or path.startswith("/api/roles/")
            or path.startswith("/api/proposals/")
            or path.startswith("/api/users/")
        ):
            await self.app(scope, receive, send)
            return

        presented_token = self._bearer_token(scope)
        token_map = self.tokens if self.tokens is not None else configured_tokens()
        role = next(
            (
                candidate_role
                for candidate_role, expected_token in token_map.items()
                if self._matches(presented_token, expected_token)
            ),
            None,
        )
        if role is None:
            response = PlainTextResponse("Unauthorized", status_code=401)
            await response(scope, receive, send)
            return

        token = current_role.set(role)
        request_body = bytearray()
        metadata_body_too_large = False
        request_headers = {key.lower(): value for key, value in scope["headers"]}
        forwarded = request_headers.get(b"cf-connecting-ip", b"").decode(
            "latin-1"
        ).strip()
        if not forwarded:
            forwarded = request_headers.get(b"x-forwarded-for", b"").decode(
                "latin-1"
            ).split(",", 1)[0].strip()
        socket_address = scope.get("client")
        last_ip = forwarded or (socket_address[0] if socket_address else None)
        is_mcp_request = path == "/mcp"
        if is_mcp_request:
            from server.members import upsert_authenticated_request

            upsert_authenticated_request(role, last_ip=last_ip)

        async def capture_receive():
            nonlocal metadata_body_too_large
            message = await receive()
            if message.get("type") == "http.request":
                chunk = message.get("body", b"")
                if len(request_body) + len(chunk) <= MAX_METADATA_BODY_SIZE:
                    request_body.extend(chunk)
                else:
                    request_body.clear()
                    metadata_body_too_large = True
                if is_mcp_request and not message.get("more_body", False):
                    metadata = (
                        (None, None, None)
                        if metadata_body_too_large
                        else _mcp_request_metadata(bytes(request_body))
                    )
                    client_name, client_version, last_tool = metadata
                    if client_name or client_version or last_tool:
                        from server.members import upsert_authenticated_request

                        upsert_authenticated_request(
                            role,
                            last_ip=None,
                            last_tool=last_tool,
                            client_name=client_name,
                            client_version=client_version,
                            count_request=False,
                        )
            return message

        try:
            await self.app(scope, capture_receive, send)
        finally:
            current_role.reset(token)

    @staticmethod
    def _bearer_token(scope: Scope) -> str | None:
        authorization = next(
            (
                value.decode("latin-1")
                for key, value in scope["headers"]
                if key.lower() == b"authorization"
            ),
            "",
        )
        scheme, _, token = authorization.partition(" ")
        return token if scheme.lower() == "bearer" and token else None

    @staticmethod
    def _matches(presented: str | None, expected: str) -> bool:
        return bool(
            presented
            and hmac.compare_digest(
                presented.encode("utf-8"), expected.encode("utf-8")
            )
        )
