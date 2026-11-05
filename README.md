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
- `check_inbox`: returns unread messages for a role and marks them read.
- `read_contract`: returns the latest contract content and version.
- `write_contract`: stores new contract content at the next version number.
- `get_thread`: returns a proposal and its linked messages in chronological order.
- `list_escalated`: returns unresolved escalated proposals with concise position summaries grouped by role.
- `human_decision`: accepts or rejects an escalated proposal and can store a decision note. It returns a clear error for an unknown proposal or one that is not escalated.

`check_inbox` and `get_thread` include a `warning` field on each message whose `contract_version` is older than the latest contract version.

Storage: SQLite (tables: contracts, messages).

## Later
- Dashboard showing each AI's activity
- One-command localhost sharing via cloudflared
- Local LLM that summarizes changes

## Known limit
An AI only acts when its human prompts it, so each AI should call `check_inbox` at the start of every task.
