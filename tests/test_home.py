from datetime import datetime, time, timedelta, timezone

from fastapi.testclient import TestClient


def test_home_endpoint(client: TestClient):
    response = client.get("/v1/home")
    assert response.status_code == 200
    payload = response.json()
    assert "now" in payload
    assert "next" in payload
    assert "upcoming" in payload
    assert "tasks" in payload
    assert "comms" in payload
    assert isinstance(payload["upcoming"], list)
    assert isinstance(payload["tasks"], dict)
    assert isinstance(payload["comms"], dict)
    assert payload["tasks"]["pending"] == 0
    assert payload["calendar"] == {
        "status": "not_connected", "today_count": 0, "next": None, "events": [], "truncated": False,
    }
    assert payload["comms"]["attention_count"] == 0


def test_home_counts_due_today_and_limits_relevant_items(client: TestClient):
    today = datetime.now(timezone.utc).date()
    due_today = datetime.combine(today, time(23, 59), tzinfo=timezone.utc)
    due_tomorrow = datetime.combine(today + timedelta(days=1), time.min, tzinfo=timezone.utc)
    tasks = [
        {"title": "Normal due today", "priority": "normal", "due": due_today.isoformat()},
        {"title": "Critical without due", "priority": "critical"},
        {"title": "High task", "priority": "high"},
        {"title": "Tomorrow", "priority": "normal", "due": due_tomorrow.isoformat()},
        {"title": "Low task", "priority": "low"},
        {"title": "Another normal", "priority": "normal"},
    ]
    for task in tasks:
        assert client.post("/v1/tasks", json=task).status_code == 201

    completed = client.post("/v1/tasks", json={"title": "Finished"})
    assert completed.status_code == 201
    assert client.patch(f"/v1/tasks/{completed.json()['id']}", json={"completed": True}).status_code == 200

    response = client.get("/v1/home")
    assert response.status_code == 200
    summary = response.json()["tasks"]
    assert summary["pending"] == 6
    assert summary["due_today"] == 1
    assert len(summary["items"]) == 5
    assert summary["items"][0]["priority"] == "critical"
    assert summary["items"][1]["priority"] == "high"
