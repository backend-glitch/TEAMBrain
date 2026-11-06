# AGENTS.md

## Project
TeamBrain: a shared context server so each teammate's AI (UI/UX, frontend, backend) can see the others' work and communicate through structured messages.

## Stack
- Python 3.11, official `mcp` SDK
- SQLite for storage
- Dashboard (later): React + Vite
- Tunnel (later): cloudflared

## Message types
`request`, `proposal`, `objection`, `accept`
Every message has: id, from_role, to_role, type, body, contract_version, created_at.

## Rules
- Keep it simple. Build only what I ask, no extra features.
- Work in small steps and explain what you changed.
- The API contract (OpenAPI file) is the source of truth.
- Any contract change increments the version number.
- Breaking changes need human approval, never auto-accept.
- Write a test for every tool.
- Update README.md if a decision changes.
- To ask for or change something, post a proposal. Reply to it with objection or accept using its proposal_id. Don't send loose requests.

## TeamBrain workflow (always follow)
- At the start of every task: call check_inbox, then get_thread for each proposal_id you were sent.
- Reply in the thread with objection or accept, using proposal_id.
- Before changing anything shared (API shape, schema), post a proposal and wait.
- Do the work the accepted proposal requires, then mark_read what you handled.
- Never edit code that contradicts the current contract.
- Breaking contract changes need a human accept.
- If a thread has 6 messages, stop and say a human is needed.

## Structure
- /server: MCP server
- /tests: tests
- /dashboard: later
