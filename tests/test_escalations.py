import pytest

from server import messages


def make_escalated_proposal(messages_module, proposal_id=None):
    proposal = messages_module.post_message(
        "frontend", "backend", "proposal", "Add cursor pagination", 2
    )
    proposal_id = proposal_id or proposal["id"]
    for number in range(3):
        messages_module.post_message(
            "backend",
            "frontend",
            "objection",
            f"Objection {number + 1}: clarify cursor behavior",
            2,
            proposal_id=proposal_id,
        )
    return proposal_id


def test_list_escalated_summarizes_each_role_position(tmp_path, monkeypatch):
    monkeypatch.setattr(messages, "DB_PATH", tmp_path / "messages.sqlite3")
    proposal_id = make_escalated_proposal(messages)

    escalated = messages.list_escalated()

    assert len(escalated) == 1
    assert escalated[0]["proposal_id"] == proposal_id
    assert escalated[0]["positions"] == [
        {"role": "frontend", "summary": "proposal: Add cursor pagination"},
        {
            "role": "backend",
            "summary": (
                "objection: Objection 1: clarify cursor behavior | "
                "objection: Objection 2: clarify cursor behavior | "
                "objection: Objection 3: clarify cursor behavior"
            ),
        },
    ]


@pytest.mark.parametrize(
    ("decision", "expected_status"),
    [("accept", "accepted"), ("reject", "rejected")],
)
def test_human_decision_resolves_escalated_proposal(
    tmp_path, monkeypatch, decision, expected_status
):
    monkeypatch.setattr(messages, "DB_PATH", tmp_path / "messages.sqlite3")
    proposal_id = make_escalated_proposal(messages)

    result = messages.human_decision(proposal_id, decision)

    assert result == {
        "proposal_id": proposal_id,
        "decision": decision,
        "status": expected_status,
        "note": None,
    }
    assert messages.get_thread(proposal_id)[0]["status"] == expected_status
    assert messages.list_escalated() == []


def test_human_decision_only_accepts_escalated_proposals(tmp_path, monkeypatch):
    monkeypatch.setattr(messages, "DB_PATH", tmp_path / "messages.sqlite3")
    proposal = messages.post_message(
        "frontend", "backend", "proposal", "Add cursor pagination", 2
    )

    with pytest.raises(ValueError, match="Only an escalated proposal"):
        messages.human_decision(proposal["id"], "accept")


def test_human_decision_persists_note(tmp_path, monkeypatch):
    monkeypatch.setattr(messages, "DB_PATH", tmp_path / "messages.sqlite3")
    proposal_id = make_escalated_proposal(messages)
    note = "Parameters undefined, backend to propose a full pagination spec first."

    result = messages.human_decision(proposal_id, "reject", note)

    assert result["note"] == note
    assert messages.get_thread(proposal_id)[0]["decision_note"] == note
