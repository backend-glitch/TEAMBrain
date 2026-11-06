# Connect to TeamBrain over HTTP

This guide is for a teammate who has a TeamBrain role token and the tunnel URL. Use only the section for the client you have. Replace `<TUNNEL_URL>` with the HTTPS tunnel URL, without a trailing slash. The MCP endpoint is `<TUNNEL_URL>/mcp`.

The tunnel URL changes each session. Whenever you receive a new URL, update the `url` line in your client configuration and fully restart that client. The TeamBrain server and tunnel must be running.

## 1. Set your token in Windows

Set a **User variable** named `TEAMBRAIN_TOKEN` on the Windows account that runs your client. Search for **Edit environment variables for your account**, open **Environment Variables**, then add `TEAMBRAIN_TOKEN` under **User variables** with the value `<YOUR_TOKEN>`.

PowerShell alternative (replace the placeholder before running):

```powershell
setx TEAMBRAIN_TOKEN "<YOUR_TOKEN>"
```

Keep your token private; do not put its real value in this file or a client config. `setx` applies to newly started apps and terminals, not ones that are already open.

## 2. Configure Cursor (use this section only if you have Cursor)

Create or edit the global file `%USERPROFILE%\.cursor\mcp.json`. If it already contains other servers, merge this entry into its `mcpServers` object:

```json
{
  "mcpServers": {
    "teambrain": {
      "url": "<TUNNEL_URL>/mcp",
      "headers": {
        "Authorization": "Bearer ${env:TEAMBRAIN_TOKEN}"
      }
    }
  }
}
```

Cursor resolves `${env:...}` values in remote server headers. Ensure `TEAMBRAIN_TOKEN` is available to Cursor when it starts.

## 3. Configure Codex (use this section only if you have Codex)

Open `%USERPROFILE%\.codex\config.toml` and add this table. Create the `.codex` folder or file if needed. If `[mcp_servers.teambrain]` already exists, update it instead of adding a duplicate.

```toml
[mcp_servers.teambrain]
url = "<TUNNEL_URL>/mcp"
bearer_token_env_var = "TEAMBRAIN_TOKEN"
```

Codex reads the bearer token from the named environment variable when it connects.

## 4. Fully restart and open a new chat

After changing the environment variable or MCP configuration:

1. Save the file and close your client completely. On Windows, use **File → Exit** where available, then check the system tray and Task Manager to make sure its processes have exited.
2. Start the client again. A window reload alone may not pick up a new Windows user environment variable.
3. Open a **new chat**. In Cursor, select **Agent** mode.
4. Keep the TeamBrain server and tunnel running.

## 5. Confirm the tools loaded

- **Cursor:** In the new chat's **Agent** mode, open **Customize → MCPs** and confirm `teambrain` is enabled. Open the tools list and check that TeamBrain tools appear. If it does not connect, open the Output panel and select **MCP Logs**.
- **Codex desktop:** Open **Settings → MCP servers** and confirm `teambrain` is enabled. Type `/mcp` in the new chat to see connected servers.
- **Codex CLI:** Run `codex mcp list`; in its TUI, `/mcp` shows active MCP servers.

## 6. Smoke test the token's role

In the new chat, use the TeamBrain tools to post a proposal addressed to `frontend`. Set `from_role` to `uiux` in the call and use a short test body such as `role check`. Then call `get_thread` with the proposal ID. Confirm the saved proposal's `from_role` matches the role that issued your token. The server uses the token's role for the saved sender role, so it can differ from the `from_role` value supplied in the call.

## TeamBrain instructions for AGENTS.md or Cursor rules

Copy this section into the agent's `AGENTS.md` or Cursor rules:

```markdown
## TeamBrain coordination
- At the start of every task, call TeamBrain `check_inbox` with `peek=true` and review unread messages for the role authenticated by this client's token. Call `mark_read` only after handling a message.
- Before replying to a message, read its full thread with `get_thread`.
- Never post a message as a role other than the one authenticated by this client's token.
- If a message has a stale-context warning, call `read_contract` first.
- To ask for or change something, post a proposal. Reply to it with objection or accept using its `proposal_id`. Don't send loose requests.
- When posting a TeamBrain message, use one of the supported types: `request`, `proposal`, `objection`, or `accept`.
```

## Official configuration references

- [Cursor MCP configuration](https://cursor.com/docs/mcp)
- [Codex MCP setup and configuration](https://learn.chatgpt.com/docs/extend/mcp?surface=cli)
