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
- `post_message`: validates and stores a typed message for a role with its `contract_version`. An optional `proposal_id` links a reply to an original proposal; standalone proposals start as their own thread root. An optional plain-text `handoff_prompt` (up to 2,000 characters) can provide task-specific instructions.
- `list_roles`: read-only list of configured roles, descriptions, colors, active flags, and contract-writing capability.
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

Dashboard role cards show the newest unread message in a “Waiting for you” box, including its handoff prompt or a generated prompt based on the message body. The box can copy the prompt and cycle through unread messages without marking them read.

In HTTP mode, `set_status` and `log_work` use the authenticated token's role. In stdio mode, pass the optional `role` argument to those tools.

Storage: SQLite locally by default, or PostgreSQL when `DATABASE_URL` is set. Both backends use the same tables: contracts, messages, team_status, status_history, work_log, members, roles, dashboard_users, and dashboard_settings. Dashboard accounts are separate from role tokens and use salted scrypt password hashes. Roles are database-backed; names use lowercase letters and digits, up to 20 characters. The default roles are `uiux`, `frontend`, and `backend`; `qa` and `database` are seeded inactive examples. The owner can activate/deactivate roles and add roles in the dashboard. Adding a role shows the matching `TEAMBRAIN_TOKEN_<ROLE>` environment variable name; the owner generates and configures the token separately. The server never generates or stores role tokens. HTTP authentication reads each active role's configured environment variable and keeps constant-time bearer comparison. Member cards support `manual` and `headless` run-mode labels (headless execution is not implemented) plus a free-text tool label. Authenticated MCP requests update per-role client activity metadata and request counts. Tokens and message bodies are never stored in member records. IP addresses and machine labels are exposed only through the dashboard, and per-role user accounts do not receive other roles' private member metadata.

## Running locally

Install the pinned dependencies with `python -m pip install -r requirements.txt`. From the project root, start the server:

- Stdio (default): `python server/app.py` or `python server/app.py --stdio`
- Streamable HTTP: `python server/app.py --http` (defaults to `http://127.0.0.1:8000/mcp`)

## Deploy free with Render and Prisma Postgres

The repository includes a Render Blueprint for a free web service. Render's local filesystem is ephemeral on the free plan, so the Blueprint requires an external PostgreSQL URL and will fail at startup if it is missing. The Python server uses `psycopg`; it does not use Prisma ORM.

1. Create a Prisma Postgres database in your Prisma account. Choose the persistent Free workspace database, not the temporary `npx create-db` database (temporary databases are deleted after 24 hours unless claimed).
2. Copy the pooled PostgreSQL connection string from Prisma's database connection page. Keep it private.
3. Commit and push the project, including `render.yaml`, to GitHub. In Render, choose **New → Blueprint**, connect the repository and branch, and create the service. When prompted for `DATABASE_URL`, paste the Prisma connection string directly into Render's secret field.
4. Render generates the session secret, dashboard password, and seeded role tokens. Keep them private. Configure MCP clients with the role token needed for each role. `TEAMBRAIN_DASHBOARD_TOKEN` is the fallback owner login password until you create an owner account.
5. Render assigns HTTPS and a public hostname. The Blueprint allows that hostname for MCP DNS-rebinding checks and enables the dashboard behind its existing login/session and Origin checks.
6. Check the Render deploy logs and open `https://<render-hostname>/healthz`. It should return `{"status":"ok"}`. MCP uses `https://<render-hostname>/mcp`.
7. If you need existing local messages and profiles, set `DATABASE_URL` in a local terminal to the same Prisma connection string and run `python -m server.migrate_sqlite_to_postgres --source <path-to-teambrain.sqlite3>` once. The migration refuses to overwrite existing target data unless you pass `--replace`.

Render Free services spin down after 15 minutes without traffic, so the first request after a pause can take about a minute. Prisma Postgres Free currently includes 200,000 operations and 2 GB storage per month; it does not include managed backups. The Render Blueprint refreshes the dashboard every 30 seconds to conserve database operations. The backup command writes timestamped `.json.gz` exports for Postgres (and SQLite online backups locally), retaining the newest seven. For dependable cloud backups, run `python -m server.backup --directory <persistent-folder>` from a machine that can reach Prisma Postgres, such as Windows Task Scheduler on your laptop. Restore a Postgres export with `python -m server.backup --restore <backup-file> --replace`; keep the backup folder private and outside the repository.

The app image runs as an unprivileged `teambrain` user and binds to `0.0.0.0`. Production enforces HTTPS via the trusted proxy, sets Secure session cookies and security headers, and retains login rate limiting. The dashboard remains session authenticated, POST actions verify Origin, and role tokens do not authenticate dashboard requests.

The dashboard is served at `/dashboard`, with JSON at `/api/dashboard`. Sign in with a username and password. The legacy `owner` login uses `TEAMBRAIN_DASHBOARD_TOKEN` as a fallback until an owner account is created; an owner can disable that fallback from the Users page. Owner accounts see the whole dashboard and manage users, while member accounts are linked to one role and can only see that role's inbox card and send tasks to it. Member API responses omit machine labels and IP addresses. Passwords are stored as salted scrypt hashes, and account management never returns passwords or hashes. Sessions are signed, HttpOnly, SameSite=Strict, and Secure in production; disabling an account invalidates its sessions on the next request. Production responses include HSTS, `X-Content-Type-Options`, `X-Frame-Options`, and a restrictive Content-Security-Policy for the self-contained dashboard. DNS rebinding protection remains enabled for MCP requests.

### Environment variables

| Variable | Purpose | Default / requirement |
| --- | --- | --- |
| `PORT` | HTTP listen port. | `8000`; integer 1–65535. |
| `HOST` | HTTP bind address. | Local mode: `127.0.0.1`; production: `0.0.0.0`. |
| `TEAMBRAIN_ENV` | Set to `production` to enable production checks, HTTPS enforcement, Secure cookies, and security headers. | Unset (local behavior). |
| `TEAMBRAIN_DB` | SQLite database path, used when `DATABASE_URL` is unset. | Local `server/teambrain.sqlite3`; configured value must be absolute. |
| `DATABASE_URL` | PostgreSQL connection string; when set, the server uses PostgreSQL instead of SQLite. Use the pooled Prisma Postgres URL for the web service. | Unset; optional locally, required by the Render Blueprint. |
| `TEAMBRAIN_REQUIRE_DATABASE_URL` | Fail startup unless `DATABASE_URL` is set. | `false`; Render Blueprint sets `true`. |
| `TEAMBRAIN_DASHBOARD_POLL_MS` | Dashboard polling interval in milliseconds (bounded to 1–300 seconds). | `3000`; Render Blueprint sets `30000` to reduce free database operations. |
| `TEAMBRAIN_ALLOWED_HOSTS` | Comma-separated allowed hostnames for MCP DNS-rebinding protection, normally the public domain. | Empty; localhost and loopback defaults remain enabled. |
| `TEAMBRAIN_TOKEN_UIUX` | Bearer token for the active `uiux` role. | Required to authenticate that role. |
| `TEAMBRAIN_TOKEN_FRONTEND` | Bearer token for the active `frontend` role. | Required to authenticate that role. |
| `TEAMBRAIN_TOKEN_BACKEND` | Bearer token for the active `backend` role. | Required to authenticate that role. |
| `TEAMBRAIN_TOKEN_<ROLE>` | Token variable for any additional role, using the variable name stored for that role. | Required only for an active role to authenticate. |
| `TEAMBRAIN_SESSION_SECRET` | Signs dashboard sessions. | Required in production; keep private and stable across restarts. |
| `TEAMBRAIN_DASHBOARD_TOKEN` | Dashboard login password, distinct from all role tokens. | Required in production. |
| `TEAMBRAIN_DASHBOARD_PUBLIC` | Allow dashboard and `/api/*` through forwarded tunnel headers. Session and Origin checks remain in force. | `false`. |

Do not put real secrets in this document, `.env` files committed to source control, Docker build arguments, or image layers. Set them through the cloud host's environment/secret configuration.

## Later
- One-command localhost sharing via cloudflared
- Local LLM that summarizes changes

## Known limit
An AI only acts when its human prompts it, so each AI should call `check_inbox` at the start of every task.
