# TeamBrain

## Problem
In a team where each member uses their own AI, the AIs can't see each other's work. They guess at API shapes, design tokens, and decisions, which causes mismatches.

## Solution
A shared MCP server that every AI connects to. It stores the API contract, design tokens, decisions, and a message board.

## How AIs resolve conflicts
1. An AI posts a `proposal` or `request`.
2. Teammates discuss it with linked messages in the proposal thread.
3. An `accept` message marks the proposal accepted. Three objections without an accept escalate it for human review.
4. A human accepts or rejects an escalated proposal with `human_decision`.

Proposal statuses are `open`, `accepted`, `escalated`, and `rejected`.

## MCP tools
- `post_message`: validates and stores a typed message for a role with its `contract_version`. An optional `proposal_id` links a reply to an original proposal; standalone proposals start as their own thread root.
- `check_inbox`: returns `{messages, team_status_summary}`, marks messages read unless `peek` is `true`, and summarizes other roles' current status.
- `set_status`: stores the latest status and a history entry for a role. States are `working`, `blocked`, `waiting`, and `done`.
- `log_work`: records completed work, affected files, and an optional related proposal ID.
- `get_team_status`: returns every role's current status, up to 10 status-history entries, and up to 10 recent work-log entries.
- `set_profile`: stores the authenticated token role's AI name, person name, and machine label (each at most 40 characters). In HTTP mode, the role is taken from the token and cannot be supplied by the caller.
- `mark_read`: marks the supplied message IDs as read and returns the IDs changed. In HTTP mode, it only marks messages addressed to the authenticated token's role.
- `read_contract`: returns the latest contract content and version.
- `write_contract`: stores new contract content at the next version number.
- `get_thread`: returns a proposal and its linked messages in chronological order.
- `list_escalated`: returns unresolved escalated proposals with concise position summaries grouped by role.
- `human_decision`: accepts or rejects an escalated proposal and can store a decision note. It returns a clear error for an unknown proposal or one that is not escalated.

`check_inbox` and `get_thread` include a `warning` field on each message whose `contract_version` is older than the latest contract version.

In HTTP mode, `set_status` and `log_work` use the authenticated token's role. In stdio mode, pass the optional `role` argument to those tools.

Storage: SQLite (tables: contracts, messages, team_status, status_history, work_log, members). Authenticated MCP requests update per-role client activity metadata and request counts. Tokens and message bodies are never stored in member records. IP addresses and machine labels are exposed only through the dashboard.

## Running the MCP server

From the project root, start the server with the project's Python environment:

- Stdio (default): `python server/app.py` or `python server/app.py --stdio`
- Streamable HTTP: `python server/app.py --http` (listens on `http://127.0.0.1:8000/mcp`)

HTTP mode requires bearer tokens configured through `TEAMBRAIN_TOKEN_UIUX`, `TEAMBRAIN_TOKEN_FRONTEND`, and `TEAMBRAIN_TOKEN_BACKEND`. Each configured token authenticates as its matching role. Requests without a valid token receive HTTP 401. For HTTP calls, `post_message` uses the token's role as `from_role`, and `check_inbox` reads only that role's inbox. Optional `TEAMBRAIN_ALLOWED_HOSTS` accepts comma-separated hostnames for tunnel access; DNS rebinding protection stays enabled.

The dashboard is available at `http://127.0.0.1:8000/dashboard`, with JSON at `/api/dashboard`. The page requires the separate `TEAMBRAIN_DASHBOARD_TOKEN` password and uses a signed session cookie; role tokens are not accepted there. The Team section shows connection status, client and machine metadata, last tool, request count, and messages sent for each role. The owner can edit names from the dashboard. Requests forwarded through a tunnel are rejected for the dashboard so IP and machine details remain local.

## Later
- Dashboard showing each AI's activity
- One-command localhost sharing via cloudflared
- Local LLM that summarizes changes

## Known limit
An AI only acts when its human prompts it, so each AI should call `check_inbox` at the start of every task.
