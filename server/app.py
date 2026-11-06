"""TeamBrain MCP server entry point."""

import argparse
import os
from typing import Literal

try:
    from mcp.server import MCPServer
except ImportError:  # Compatibility with MCP SDK v1.
    from mcp.server.fastmcp import FastMCP as MCPServer

from server.messages import (
    check_inbox,
    get_thread,
    get_team_status,
    human_decision,
    list_escalated,
    log_work as record_work,
    mark_read as mark_read_messages,
    post_message,
    read_contract,
    set_status as record_status,
    write_contract,
)
from server.http_auth import BearerRoleMiddleware, configured_tokens, current_role
from server.http_security import transport_security_settings
from server.members import set_profile as update_profile
from server.dashboard import (
    dashboard_api,
    dashboard_login,
    dashboard_logout,
    dashboard_page,
    dashboard_update_member,
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
) -> dict[str, object]:
    """Read unread messages and return a compact status view of teammates."""
    authenticated_role = current_role.get()
    role = authenticated_role or to_role
    team = get_team_status()["roles"]
    team_status_summary = []
    for member in team:
        if member["role"] == role:
            continue
        status = member["current_status"]
        if status is None:
            team_status_summary.append(
                {
                    "role": member["role"],
                    "state": None,
                    "summary": "No status posted",
                    "task": None,
                }
            )
        else:
            team_status_summary.append(
                {
                    "role": member["role"],
                    "state": status["state"],
                    "summary": status["summary"],
                    "task": status["task"],
                }
            )
    return {
        "messages": check_inbox(to_role=role, peek=peek),
        "team_status_summary": team_status_summary,
    }


def _status_role(requested_role: str | None) -> str:
    """Use the token identity in HTTP, with an explicit role for stdio calls."""
    authenticated_role = current_role.get()
    role = authenticated_role or requested_role
    if role is None:
        raise ValueError("role is required for stdio calls")
    return role


def set_status_tool(
    summary: str,
    state: Literal["working", "blocked", "waiting", "done"],
    task: str,
    role: str | None = None,
) -> dict[str, str]:
    """Set progress for the token role; pass role for unauthenticated stdio."""
    return record_status(_status_role(role), summary=summary, state=state, task=task)


def log_work_tool(
    summary: str,
    files: list[str],
    related_proposal_id: str | None = None,
    role: str | None = None,
) -> dict[str, str | list[str] | None]:
    """Record finished work for the token role; pass role for stdio calls."""
    return record_work(
        _status_role(role),
        summary=summary,
        files=files,
        related_proposal_id=related_proposal_id,
    )


def get_team_status_tool() -> dict[str, list[dict[str, object]]]:
    """Return every role's current status, recent status history, and work log."""
    return get_team_status()


def set_profile_tool(
    ai_name: str, person_name: str, machine_label: str
) -> dict[str, str | bool]:
    """Set the profile for the role authenticated by the caller's token."""
    role = current_role.get()
    if role is None:
        raise PermissionError("set_profile requires an authenticated role token")
    update_profile(role, ai_name, person_name, machine_label)
    return {"role": role, "updated": True}


def mark_read_tool(message_ids: list[str]) -> dict[str, list[str]]:
    """Mark only messages addressed to the authenticated role as read."""
    authenticated_role = current_role.get()
    if authenticated_role is None:
        raise PermissionError("mark_read requires an authenticated role")
    return mark_read_messages(message_ids, to_role=authenticated_role)


mcp.tool(name="post_message")(post_message_tool)
mcp.tool(name="check_inbox")(check_inbox_tool)
mcp.tool(name="set_status")(set_status_tool)
mcp.tool(name="log_work")(log_work_tool)
mcp.tool(name="get_team_status")(get_team_status_tool)
mcp.tool(name="set_profile")(set_profile_tool)
mcp.tool()(get_thread)
mcp.tool()(list_escalated)
mcp.tool()(human_decision)
mcp.tool(name="mark_read")(mark_read_tool)
mcp.tool()(read_contract)
mcp.tool()(write_contract)


def create_http_app():
    """Build the authenticated Streamable HTTP app and protected dashboard routes."""
    app = mcp.streamable_http_app(
        host="127.0.0.1",
        streamable_http_path="/mcp",
        transport_security=transport_security_settings(),
    )
    app.add_route("/dashboard", dashboard_page, methods=["GET"])
    app.add_route("/api/dashboard", dashboard_api, methods=["GET"])
    app.add_route("/api/members/{role}", dashboard_update_member, methods=["POST"])
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
