# Connecting Cursor and Codex to TeamBrain

This guide connects Cursor and Codex to the same TeamBrain HTTP server. It assumes both apps run on the Windows computer hosting the server.

## Shared server URL

Use this Streamable HTTP URL in both clients:

```text
http://127.0.0.1:8000/mcp
```

Start the server from the project root in PowerShell:

```powershell
.\.venv-win\Scripts\python.exe server\app.py --http
```

Keep that process running while using either client. `127.0.0.1` is local to this computer; for clients on other computers, use a reachable tunnel URL and allowlist its hostname with `TEAMBRAIN_ALLOWED_HOSTS`.

## Set the Windows user environment variables

TeamBrain authenticates tokens as roles. Use the frontend token for Cursor and the backend token for Codex. The server also reads the UI/UX token if that role is used.

1. In Windows, search for **Edit environment variables for your account** and open it.
2. Under **User variables**, add or update these variables with the corresponding token values:

   | Variable name | Role / use |
   | --- | --- |
   | `TEAMBRAIN_TOKEN_FRONTEND` | Cursor |
   | `TEAMBRAIN_TOKEN_BACKEND` | Codex |
   | `TEAMBRAIN_TOKEN_UIUX` | UI/UX clients, if used |

3. Save the changes, then close and reopen Cursor, Codex, and any terminal used to start the server so they inherit the updated environment.

Do not put token values in this file or commit them to the repository.

## Configure Cursor

Create or merge this entry in the project file `.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "teambrain": {
      "url": "http://127.0.0.1:8000/mcp",
      "headers": {
        "Authorization": "Bearer ${env:TEAMBRAIN_TOKEN_FRONTEND}"
      }
    }
  }
}
```

Cursor resolves `${env:NAME}` references in MCP configuration fields, including headers. Restart Cursor after changing `mcp.json` or the environment.

## Configure Codex

Add this table to `%USERPROFILE%\.codex\config.toml`:

```toml
[mcp_servers.teambrain]
url = "http://127.0.0.1:8000/mcp"
bearer_token_env_var = "TEAMBRAIN_TOKEN_BACKEND"
```

If the file already has a `[mcp_servers.teambrain]` table for stdio, replace that table instead of adding a duplicate. Restart Codex after changing `config.toml` or the environment.

## Confirm the tools loaded

- **Cursor:** Open **Customize → MCPs** and confirm `teambrain` is enabled. In the Cursor CLI, `cursor-agent mcp list` shows server status and `cursor-agent mcp list-tools teambrain` lists its tools.
- **Codex:** Open **Settings → MCP servers** and confirm `teambrain` is enabled. In the Codex CLI, run `codex mcp list`; in the Codex composer, `/mcp` shows active MCP servers.
- In either client, ask it to call TeamBrain's `read_contract` tool and report the contract version. A successful response confirms the server is reachable and authenticated.

Role-bound behavior follows the token: Cursor's frontend token identifies messages as `frontend` and scopes its inbox to `frontend`; Codex's backend token does the same for `backend`.

## References

- [Cursor MCP configuration](https://cursor.com/docs/mcp)
- [Codex MCP configuration](https://learn.chatgpt.com/docs/extend/mcp?surface=cli)
