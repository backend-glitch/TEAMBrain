import pytest
from starlette.testclient import TestClient

from server import app as app_module
from server import messages


@pytest.fixture
def dashboard_client(tmp_path, monkeypatch):
    monkeypatch.setattr(messages, "DB_PATH", tmp_path / "dashboard.sqlite3")
    monkeypatch.setenv("TEAMBRAIN_TOKEN_FRONTEND", "frontend-role-token")
    monkeypatch.setenv("TEAMBRAIN_TOKEN_BACKEND", "backend-role-token")
    monkeypatch.setenv("TEAMBRAIN_TOKEN_UIUX", "uiux-role-token")
    monkeypatch.setenv("TEAMBRAIN_DASHBOARD_TOKEN", "dashboard-only-token")

    messages.write_contract("Dashboard contract")
    proposal = messages.post_message(
        "backend", "frontend", "proposal", "<script>alert('x')</script>", 1
    )
    for number in range(3):
        messages.post_message(
            "frontend",
            "backend",
            "objection",
            f"Objection {number + 1}",
            1,
            proposal_id=proposal["id"],
        )

    app = app_module.create_http_app()
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        yield client, proposal["id"]


def test_dashboard_routes_require_a_token(dashboard_client):
    client, _ = dashboard_client

    assert client.get("/dashboard").status_code == 401
    assert client.get("/api/dashboard").status_code == 401


def test_role_tokens_are_rejected_by_dashboard_routes(dashboard_client):
    client, _ = dashboard_client

    for role_token in (
        "frontend-role-token",
        "backend-role-token",
        "uiux-role-token",
    ):
        headers = {"Authorization": f"Bearer {role_token}"}
        assert client.get("/dashboard", headers=headers).status_code == 401
        assert client.get("/api/dashboard", headers=headers).status_code == 401


def test_dashboard_token_returns_page_and_read_only_json(dashboard_client):
    client, proposal_id = dashboard_client
    headers = {"Authorization": "Bearer dashboard-only-token"}

    page_response = client.get("/dashboard", headers=headers)
    api_response = client.get("/api/dashboard", headers=headers)

    assert page_response.status_code == 200
    assert api_response.status_code == 200
    payload = api_response.json()
    assert payload["contract_version"] == 1
    proposal = next(item for item in payload["proposals"] if item["id"] == proposal_id)
    assert proposal["status"] == "escalated"
    assert len(proposal["thread"]) == 4
    assert [item["id"] for item in payload["escalated_proposals"]] == [proposal_id]


def test_script_message_is_returned_as_data_and_page_uses_text_content(dashboard_client):
    client, proposal_id = dashboard_client
    headers = {"Authorization": "Bearer dashboard-only-token"}

    payload = client.get("/api/dashboard", headers=headers).json()
    proposal = next(item for item in payload["proposals"] if item["id"] == proposal_id)
    script_message = proposal["thread"][0]["body"]
    page = client.get("/dashboard", headers=headers).text

    assert script_message == "<script>alert('x')</script>"
    assert "textContent" in page
    assert ".innerHTML" not in page
    assert script_message not in page
    assert 'fetch("/api/dashboard"' in page
    assert '"Authorization": `Bearer ${token}`' in page
    assert "localStorage" not in page


def test_dashboard_token_does_not_authenticate_mcp_route(dashboard_client):
    client, _ = dashboard_client

    response = client.post(
        "/mcp",
        headers={"Authorization": "Bearer dashboard-only-token"},
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
    )

    assert response.status_code == 401
