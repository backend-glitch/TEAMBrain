"""TeamBrain MCP server entry point."""

try:
    from mcp.server import MCPServer
except ImportError:  # Compatibility with MCP SDK v1.
    from mcp.server.fastmcp import FastMCP as MCPServer

from server.messages import (
    check_inbox,
    get_thread,
    human_decision,
    list_escalated,
    post_message,
    read_contract,
    write_contract,
)

mcp = MCPServer("TeamBrain")
mcp.tool()(post_message)
mcp.tool()(check_inbox)
mcp.tool()(get_thread)
mcp.tool()(list_escalated)
mcp.tool()(human_decision)
mcp.tool()(read_contract)
mcp.tool()(write_contract)


if __name__ == "__main__":
    mcp.run(transport="stdio")
