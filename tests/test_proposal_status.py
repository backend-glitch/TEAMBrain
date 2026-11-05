from server import messages


def test_accept_message_marks_proposal_accepted(tmp_path, monkeypatch):
    monkeypatch.setattr(messages, "DB_PATH", tmp_path / "messages.sqlite3")
    proposal = messages.post_message(
        "frontend", "backend", "proposal", "Add pagination", 1
    )

    messages.post_message(
        "backend",
        "frontend",
        "accept",
        "Agreed",
        1,
        proposal_id=proposal["id"],
    )

    thread = messages.get_thread(proposal["id"])
    assert thread[0]["status"] == "accepted"


def test_third_objection_marks_unaccepted_proposal_escalated(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(messages, "DB_PATH", tmp_path / "messages.sqlite3")
    proposal = messages.post_message(
        "frontend", "backend", "proposal", "Add pagination", 1
    )

    for number in range(3):
        messages.post_message(
            "backend",
            "frontend",
            "objection",
            f"Concern {number + 1}",
            1,
            proposal_id=proposal["id"],
        )

    thread = messages.get_thread(proposal["id"])
    assert thread[0]["status"] == "escalated"
