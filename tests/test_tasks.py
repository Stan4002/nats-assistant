from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from nats_assistant.api.server import create_app
from nats_assistant.config import Settings


def test_create_task_returns_generated_fields(client: TestClient):
    due = "2026-10-05T14:00:00+02:00"
    response = client.post(
        "/v1/tasks",
        json={"title": "Finish presentation", "priority": "high", "due": due},
    )

    assert response.status_code == 201
    task = response.json()
    assert task["title"] == "Finish presentation"
    assert task["completed"] is False
    assert task["priority"] == "high"
    assert task["source"] == "nats"
    assert task["due"] == "2026-10-05T12:00:00Z"
    assert task["id"]
    assert datetime.fromisoformat(task["created_at"].replace("Z", "+00:00")).tzinfo is not None
    assert task["created_at"] == task["updated_at"]


def test_rejects_blank_title(client: TestClient):
    response = client.post("/v1/tasks", json={"title": "   "})
    assert response.status_code == 422


def test_rejects_unsupported_priority(client: TestClient):
    response = client.post("/v1/tasks", json={"title": "Task", "priority": "urgent"})
    assert response.status_code == 422


def test_rejects_naive_due_datetime(client: TestClient):
    response = client.post("/v1/tasks", json={"title": "Task", "due": "2026-10-05T14:00:00"})
    assert response.status_code == 422


def test_list_get_update_and_complete_task(client: TestClient):
    created = client.post("/v1/tasks", json={"title": "Original", "priority": "normal"})
    assert created.status_code == 201
    task_id = created.json()["id"]

    assert client.get(f"/v1/tasks/{task_id}").json()["title"] == "Original"
    listed = client.get("/v1/tasks")
    assert listed.status_code == 200
    assert [task["id"] for task in listed.json()] == [task_id]

    updated = client.patch(f"/v1/tasks/{task_id}", json={"title": "Revised", "priority": "critical"})
    assert updated.status_code == 200
    assert updated.json()["title"] == "Revised"
    assert updated.json()["priority"] == "critical"
    assert datetime.fromisoformat(updated.json()["updated_at"].replace("Z", "+00:00")) > datetime.fromisoformat(
        created.json()["updated_at"].replace("Z", "+00:00")
    )

    completed = client.patch(f"/v1/tasks/{task_id}", json={"completed": True})
    assert completed.status_code == 200
    assert completed.json()["completed"] is True
    assert client.get("/v1/tasks?completed=true").json()[0]["id"] == task_id
    assert client.get("/v1/tasks?completed=false").json() == []


def test_patch_can_clear_description_and_due(client: TestClient):
    created = client.post(
        "/v1/tasks",
        json={"title": "Task", "description": "Details", "due": "2026-10-05T14:00:00+02:00"},
    )
    task_id = created.json()["id"]

    response = client.patch(f"/v1/tasks/{task_id}", json={"description": None, "due": None})

    assert response.status_code == 200
    assert response.json()["description"] is None
    assert response.json()["due"] is None


def test_empty_patch_is_rejected(client: TestClient):
    task_id = client.post("/v1/tasks", json={"title": "Task"}).json()["id"]
    assert client.patch(f"/v1/tasks/{task_id}", json={}).status_code == 422


def test_delete_and_missing_task_responses(client: TestClient):
    task_id = client.post("/v1/tasks", json={"title": "Delete me"}).json()["id"]

    deleted = client.delete(f"/v1/tasks/{task_id}")
    assert deleted.status_code == 204
    assert client.get(f"/v1/tasks/{task_id}").status_code == 404
    assert client.patch(f"/v1/tasks/{task_id}", json={"completed": True}).status_code == 404
    assert client.delete(f"/v1/tasks/{task_id}").status_code == 404


def test_list_orders_open_tasks_by_due_before_completed(client: TestClient):
    tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    today = datetime.now(timezone.utc).isoformat()
    completed = client.post("/v1/tasks", json={"title": "Completed", "due": today}).json()
    client.patch(f"/v1/tasks/{completed['id']}", json={"completed": True})
    no_due = client.post("/v1/tasks", json={"title": "No due"}).json()
    due_tomorrow = client.post("/v1/tasks", json={"title": "Tomorrow", "due": tomorrow}).json()
    due_today = client.post("/v1/tasks", json={"title": "Today", "due": today}).json()

    listed = client.get("/v1/tasks")

    assert listed.status_code == 200
    assert [task["id"] for task in listed.json()] == [
        due_today["id"],
        due_tomorrow["id"],
        no_due["id"],
        completed["id"],
    ]


def test_tasks_persist_across_app_restart(tmp_path):
    settings = Settings(data_dir=tmp_path / "persistent-data", timezone="UTC")
    with TestClient(create_app(settings)) as first_client:
        created = first_client.post("/v1/tasks", json={"title": "Persist me"})
        assert created.status_code == 201
        task_id = created.json()["id"]

    with TestClient(create_app(settings)) as second_client:
        response = second_client.get(f"/v1/tasks/{task_id}")

    assert response.status_code == 200
    assert response.json()["title"] == "Persist me"
