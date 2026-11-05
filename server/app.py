"""TeamBrain MCP server entry point."""

import argparse
import os

try:
    from mcp.server import MCPServer
except ImportError:  # Compatibility with MCP SDK v1.
    from mcp.server.fastmcp import FastMCP as MCPServer

from server.messages import (
    check_inbox,
    get_thread,
    human_decision,
    list_escalated,
    mark_read as mark_read_messages,
    post_message,
    read_contract,
    write_contract,
)
from server.http_auth import BearerRoleMiddleware, configured_tokens, current_role
from server.http_security import transport_security_settings
from server.dashboard import (
    dashboard_api,
    dashboard_login,
    dashboard_logout,
    dashboard_page,
)

mcp = MCPServer("TeamBrain")


def post_message_tool(
    from_role: str,
    to_role: str,
    type: str,
    body: str,
    contract_version: int,
    proposal_id: str | None = None,
) -> dict[str, str | int | None]:
    """Post a message, using the authenticated role for HTTP requests."""
    authenticated_role = current_role.get()
    return post_message(
        from_role=authenticated_role or from_role,
        to_role=to_role,
        type=type,
        body=body,
        contract_version=contract_version,
        proposal_id=proposal_id,
    )


def check_inbox_tool(
    to_role: str, peek: bool = False
) -> list[dict[str, str | int | None]]:
    """Read the authenticated role's inbox for HTTP requests."""
    authenticated_role = current_role.get()
    return check_inbox(to_role=authenticated_role or to_role, peek=peek)


def mark_read_tool(message_ids: list[str]) -> dict[str, list[str]]:
    """Mark only messages addressed to the authenticated role as read."""
    authenticated_role = current_role.get()
    if authenticated_role is None:
        raise PermissionError("mark_read requires an authenticated role")
    return mark_read_messages(message_ids, to_role=authenticated_role)


mcp.tool(name="post_message")(post_message_tool)
mcp.tool(name="check_inbox")(check_inbox_tool)
mcp.tool()(get_thread)
mcp.tool()(list_escalated)
mcp.tool()(human_decision)
mcp.tool(name="mark_read")(mark_read_tool)
mcp.tool()(read_contract)
mcp.tool()(write_contract)


def create_http_app():
    """Build the authenticated Streamable HTTP app with read-only dashboard routes."""
    app = mcp.streamable_http_app(
        host="127.0.0.1",
        streamable_http_path="/mcp",
        transport_security=transport_security_settings(),
    )
    app.add_route("/dashboard", dashboard_page, methods=["GET"])
    app.add_route("/api/dashboard", dashboard_api, methods=["GET"])
    app.add_route("/api/login", dashboard_login, methods=["POST"])
    app.add_route("/api/logout", dashboard_logout, methods=["POST"])
    app.add_middleware(
        BearerRoleMiddleware,
        tokens=configured_tokens(),
        dashboard_token=os.environ.get("TEAMBRAIN_DASHBOARD_TOKEN"),
    )
    return app


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the TeamBrain MCP server.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--http",
        action="store_true",
        help="Use Streamable HTTP at http://127.0.0.1:8000/mcp.",
    )
    mode.add_argument(
        "--stdio",
        action="store_true",
        help="Use stdio transport (the default).",
    )
    args = parser.parse_args()

    if args.http:
        import uvicorn

        uvicorn.run(create_http_app(), host="127.0.0.1", port=8000)
    else:
        mcp.run(transport="stdio")
