"""TeamBrain MCP server entry point."""

try:
    from mcp.server import MCPServer
except ImportError:  # Compatibility with MCP SDK v1.
    from mcp.server.fastmcp import FastMCP as MCPServer

from server.messages import check_inbox, get_thread, post_message, read_contract

mcp = MCPServer("TeamBrain")
mcp.tool()(post_message)
mcp.tool()(check_inbox)
mcp.tool()(get_thread)
mcp.tool()(read_contract)


if __name__ == "__main__":
    mcp.run(transport="stdio")
