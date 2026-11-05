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
    """Require a configured bearer token and bind its role to the request."""

    def __init__(self, app: ASGIApp, tokens: dict[str, str]):
        self.app = app
        self.tokens = tokens

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        authorization = next(
            (
                value.decode("latin-1")
                for key, value in scope["headers"]
                if key.lower() == b"authorization"
            ),
            "",
        )
        scheme, _, presented_token = authorization.partition(" ")
        role = next(
            (
                candidate_role
                for candidate_role, expected_token in self.tokens.items()
                if scheme.lower() == "bearer"
                and presented_token
                and hmac.compare_digest(
                    presented_token.encode("utf-8"), expected_token.encode("utf-8")
                )
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
