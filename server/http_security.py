"""Transport security configuration for TeamBrain's HTTP endpoint."""

import base64
import hashlib
import os
import re
from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from mcp.server.transport_security import TransportSecuritySettings


BASE_ALLOWED_HOSTS = ["127.0.0.1:*", "localhost:*"]
BASE_ALLOWED_ORIGINS = ["http://127.0.0.1:*", "http://localhost:*"]


class ProductionSecurityMiddleware:
    """Require HTTPS in production and apply browser security headers."""

    def __init__(self, app: ASGIApp, production: bool = False):
        self.app = app
        self.production = production
        self.content_security_policy = dashboard_content_security_policy()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        forwarded_proto = headers.get(b"x-forwarded-proto", b"").decode(
            "latin-1"
        ).split(",", 1)[0].strip().lower()
        is_https = forwarded_proto == "https" or (
            not forwarded_proto and scope.get("scheme") == "https"
        )

        async def send_with_security_headers(message):
            if message.get("type") == "http.response.start":
                response_headers = list(message.get("headers", []))
                existing = {key.lower() for key, _ in response_headers}
                security = [
                    (b"x-content-type-options", b"nosniff"),
                    (b"x-frame-options", b"DENY"),
                    (
                        b"content-security-policy",
                        self.content_security_policy.encode("ascii"),
                    ),
                ]
                if self.production:
                    security.append(
                        (
                            b"strict-transport-security",
                            b"max-age=31536000; includeSubDomains",
                        )
                    )
                response_headers.extend(
                    (key, value) for key, value in security if key not in existing
                )
                message = {**message, "headers": response_headers}
            await send(message)

        if self.production and not is_https:
            await PlainTextResponse("HTTPS is required", status_code=400)(
                scope, receive, send_with_security_headers
            )
            return

        await self.app(scope, receive, send_with_security_headers)


def request_is_https(request) -> bool:
    """Honor the proxy's X-Forwarded-Proto when deciding cookie security."""
    forwarded_proto = request.headers.get("x-forwarded-proto", "")
    scheme = forwarded_proto.split(",", 1)[0].strip().lower()
    return scheme == "https" if scheme else request.url.scheme == "https"


def dashboard_content_security_policy() -> str:
    """Allow only the dashboard's exact inline script and stylesheet blocks."""
    from server.dashboard_ui import DASHBOARD_HTML
    from server.deployment import dashboard_poll_ms

    dashboard_html = DASHBOARD_HTML.replace(
        "__TEAMBRAIN_DASHBOARD_POLL_MS__", str(dashboard_poll_ms())
    )

    directives = {"script-src": [], "style-src": []}
    for tag, directive in (("script", "script-src"), ("style", "style-src")):
        for content in re.findall(
            rf"<{tag}>(.*?)</{tag}>", dashboard_html, flags=re.DOTALL
        ):
            digest = base64.b64encode(
                hashlib.sha256(content.encode("utf-8")).digest()
            ).decode("ascii")
            directives[directive].append(f"'sha256-{digest}'")
    return "; ".join(
        (
            "default-src 'none'",
            f"script-src 'self' {' '.join(directives['script-src'])}",
            f"style-src 'self' {' '.join(directives['style-src'])}",
            "style-src-attr 'unsafe-inline'",
            "connect-src 'self'",
            "img-src 'self' data:",
            "form-action 'self'",
            "base-uri 'none'",
            "frame-ancestors 'none'",
        )
    )


def transport_security_settings(
    allowed_hosts_env: str | None = None,
) -> TransportSecuritySettings:
    """Build SDK DNS-rebinding settings, including optional tunnel hostnames."""
    configured = (
        os.environ.get("TEAMBRAIN_ALLOWED_HOSTS", "")
        if allowed_hosts_env is None
        else allowed_hosts_env
    )
    hostnames = list(dict.fromkeys(
        hostname.strip()
        for hostname in configured.split(",")
        if hostname.strip()
    ))

    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[
            *BASE_ALLOWED_HOSTS,
            *(entry for hostname in hostnames for entry in (hostname, f"{hostname}:*")),
        ],
        allowed_origins=[
            *BASE_ALLOWED_ORIGINS,
            *(
                entry
                for hostname in hostnames
                for entry in (f"https://{hostname}", f"https://{hostname}:*")
            ),
        ],
    )
