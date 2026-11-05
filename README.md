# TeamBrain

## Problem
In a team where each member uses their own AI, the AIs can't see each other's work. They guess at API shapes, design tokens, and decisions, which causes mismatches.

## Solution
A shared MCP server that every AI connects to. It stores the API contract, design tokens, decisions, and a message board.

## How AIs resolve conflicts
1. An AI posts a `proposal` or `request`.
2. If it breaks nobody's work, it's auto-accepted.
3. If it does, the affected AI replies with an `objection`.
4. After 3 rounds with no agreement, humans get a summary and decide.

## MVP scope
Tools:
- `read_contract`: returns the current contract and version
- `post_message`: sends a typed message to a role
- `check_inbox`: returns unread messages for a role

Storage: SQLite (tables: contracts, messages).

## Later
- Dashboard showing each AI's activity
- One-command localhost sharing via cloudflared
- Local LLM that summarizes changes

## Known limit
An AI only acts when its human prompts it, so each AI should call `check_inbox` at the start of every task.
