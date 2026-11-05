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

## Structure
- /server: MCP server
- /tests: tests
- /dashboard: later
