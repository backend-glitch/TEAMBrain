"""Bearer token authentication for TeamBrain's HTTP transport."""

import hmac
import os
from contextvars import ContextVar
from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send


current_role: ContextVar[str | None] = ContextVar("teambrain_current_role", default=None)

TOKEN_ENV_BY_ROLE = {
    "uiux": "TEAMBRAIN_TOKEN_UIUX",
    "frontend": "TEAMBRAIN_TOKEN_FRONTEND",
    "backend": "TEAMBRAIN_TOKEN_BACKEND",
}


def configured_tokens() -> dict[str, str]:
    """Load configured role tokens, omitting unset or empty values."""
    return {
        role: token
        for role, variable in TOKEN_ENV_BY_ROLE.items()
        if (token := os.environ.get(variable))
    }


class BearerRoleMiddleware:
    """Authenticate dashboard and MCP routes with separate bearer tokens."""

    DASHBOARD_PATHS = {
        "/dashboard",
        "/api/dashboard",
        "/api/login",
        "/api/logout",
    }

    def __init__(
        self,
        app: ASGIApp,
        tokens: dict[str, str],
        dashboard_token: str | None = None,
    ):
        self.app = app
        self.tokens = tokens
        self.dashboard_token = dashboard_token
        if dashboard_token and dashboard_token in tokens.values():
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
                b"cf-connecting-ip" in forwarded_headers
                or b"x-forwarded-for" in forwarded_headers
            ):
                await PlainTextResponse("Forbidden", status_code=403)(
                    scope, receive, send
                )
                return

        if path in self.DASHBOARD_PATHS:
            await self.app(scope, receive, send)
            return

        presented_token = self._bearer_token(scope)
        role = next(
            (
                candidate_role
                for candidate_role, expected_token in self.tokens.items()
                if self._matches(presented_token, expected_token)
            ),
            None,
        )
        if role is None:
            response = PlainTextResponse("Unauthorized", status_code=401)
            await response(scope, receive, send)
            return

        token = current_role.set(role)
        try:
            await self.app(scope, receive, send)
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
