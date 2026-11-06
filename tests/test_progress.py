import pytest

from server import app as app_module
from server import messages
from server.http_auth import current_role


def test_set_status_keeps_latest_value_and_recent_history(tmp_path, monkeypatch):
    monkeypatch.setattr(messages, "DB_PATH", tmp_path / "progress.sqlite3")

    for number in range(12):
        status = messages.set_status(
            "frontend", f"Update {number}", "working", f"Task {number}"
        )

    result = messages.get_team_status()
    roles = {entry["role"]: entry for entry in result["roles"]}

    assert set(roles) == {"uiux", "frontend", "backend"}
    frontend = roles["frontend"]
    assert frontend["current_status"] == status
    assert len(frontend["status_history"]) == 10
    assert frontend["status_history"][0]["summary"] == "Update 11"
    assert frontend["status_history"][-1]["summary"] == "Update 2"
    assert roles["uiux"]["current_status"] is None
    assert roles["uiux"]["work_log"] == []


def test_set_status_rejects_unknown_role_and_state(tmp_path, monkeypatch):
    monkeypatch.setattr(messages, "DB_PATH", tmp_path / "progress.sqlite3")

    with pytest.raises(ValueError, match="Invalid role"):
        messages.set_status("designer", "Working", "working", "Design")
    with pytest.raises(ValueError, match="Invalid state"):
        messages.set_status("uiux", "Working", "paused", "Design")


def test_log_work_stores_files_and_related_proposal(tmp_path, monkeypatch):
    monkeypatch.setattr(messages, "DB_PATH", tmp_path / "progress.sqlite3")

    entry = messages.log_work(
        "backend",
        "Added status persistence",
        ["server/database.py", "server/messages.py"],
        related_proposal_id="proposal-123",
    )

    backend = next(
        role for role in messages.get_team_status()["roles"] if role["role"] == "backend"
    )
    assert backend["work_log"] == [entry]
    assert entry["files"] == ["server/database.py", "server/messages.py"]
    assert entry["related_proposal_id"] == "proposal-123"


def test_log_work_returns_only_the_last_ten_entries(tmp_path, monkeypatch):
    monkeypatch.setattr(messages, "DB_PATH", tmp_path / "progress.sqlite3")

    for number in range(12):
        messages.log_work("frontend", f"Finished {number}", [f"file-{number}.py"])

    frontend = next(
        role for role in messages.get_team_status()["roles"] if role["role"] == "frontend"
    )
    work_log = frontend["work_log"]

    assert len(work_log) == 10
    assert {entry["summary"] for entry in work_log} == {
        f"Finished {number}" for number in range(2, 12)
    }


def test_http_token_role_overrides_requested_stdio_role(tmp_path, monkeypatch):
    monkeypatch.setattr(messages, "DB_PATH", tmp_path / "progress.sqlite3")
    token_role = current_role.set("frontend")
    try:
        status = app_module.set_status_tool(
            "Building UI",
            "working",
            "Add inbox view",
            role="backend",
        )
        work = app_module.log_work_tool(
            "Updated inbox view",
            ["client/inbox.py"],
            role="backend",
        )
    finally:
        current_role.reset(token_role)

    assert status["role"] == "frontend"
    assert work["role"] == "frontend"


def test_stdio_calls_can_supply_a_role(tmp_path, monkeypatch):
    monkeypatch.setattr(messages, "DB_PATH", tmp_path / "progress.sqlite3")

    status = app_module.set_status_tool(
        "Reviewing API", "waiting", "Need backend response", role="uiux"
    )
    work = app_module.log_work_tool(
        "Finished wireframes", ["design/home.png"], role="uiux"
    )

    assert status["role"] == "uiux"
    assert work["role"] == "uiux"


def test_check_inbox_includes_other_roles_status_summary(tmp_path, monkeypatch):
    monkeypatch.setattr(messages, "DB_PATH", tmp_path / "progress.sqlite3")
    messages.set_status("backend", "Implementing auth", "working", "Session API")
    messages.set_status("uiux", "Reviewing layout", "waiting", "Dashboard review")
    message = messages.post_message(
        "backend", "frontend", "request", "Please review this", 1
    )

    result = app_module.check_inbox_tool(to_role="frontend", peek=True)

    assert [item["id"] for item in result["messages"]] == [message["id"]]
    assert result["team_status_summary"] == [
        {
            "role": "uiux",
            "state": "waiting",
            "summary": "Reviewing layout",
            "task": "Dashboard review",
        },
        {
            "role": "backend",
            "state": "working",
            "summary": "Implementing auth",
            "task": "Session API",
        },
    ]
