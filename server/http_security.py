"""Transport security configuration for TeamBrain's HTTP endpoint."""

import os

from mcp.server.transport_security import TransportSecuritySettings


BASE_ALLOWED_HOSTS = ["127.0.0.1:*", "localhost:*"]
BASE_ALLOWED_ORIGINS = ["http://127.0.0.1:*", "http://localhost:*"]


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
