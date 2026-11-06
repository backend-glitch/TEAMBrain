"""Runtime settings and production safety checks."""

import os


def production_mode() -> bool:
    return os.environ.get("TEAMBRAIN_ENV", "").strip().lower() == "production"


def validate_startup_config() -> None:
    """Fail early with actionable errors for required production secrets."""
    if not production_mode():
        return
    missing = [
        name
        for name in ("TEAMBRAIN_SESSION_SECRET", "TEAMBRAIN_DASHBOARD_TOKEN")
        if not os.environ.get(name)
    ]
    require_postgres = os.environ.get(
        "TEAMBRAIN_REQUIRE_DATABASE_URL", "false"
    ).strip().lower() in {"1", "true", "yes", "on"}
    if require_postgres and not os.environ.get("DATABASE_URL", "").strip():
        missing.append("DATABASE_URL")
    if missing:
        raise RuntimeError(
            "Production startup requires environment variable(s): "
            + ", ".join(missing)
        )


def server_host() -> str:
    return os.environ.get("HOST") or (
        "0.0.0.0" if production_mode() else "127.0.0.1"
    )


def server_port() -> int:
    raw_port = os.environ.get("PORT", "8000")
    try:
        port = int(raw_port)
    except ValueError as error:
        raise RuntimeError("PORT must be an integer from 1 to 65535") from error
    if not 1 <= port <= 65535:
        raise RuntimeError("PORT must be an integer from 1 to 65535")
    return port


def dashboard_public() -> bool:
    return os.environ.get("TEAMBRAIN_DASHBOARD_PUBLIC", "false").strip().lower() in {
        "1", "true", "yes", "on"
    }


def dashboard_poll_ms() -> int:
    """Return the dashboard refresh interval, with safe bounds for hosted tiers."""
    try:
        value = int(os.environ.get("TEAMBRAIN_DASHBOARD_POLL_MS", "3000"))
    except ValueError:
        return 3000
    return min(300_000, max(1_000, value))
