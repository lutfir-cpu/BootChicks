import json
import time

from fastapi.testclient import TestClient

from bootchicks.api import create_app


def finished(client, run_id):
    for _ in range(100):
        state = client.get(f"/runs/{run_id}").json()
        if state["status"] not in ["QUEUED", "RUNNING"]:
            return state
        time.sleep(0.01)
    raise AssertionError("Local stub run did not finish.")


def test_http_submission_idempotency_export_and_persistence(tmp_path):
    database = tmp_path / "http.sqlite"
    with TestClient(create_app(database)) as client:
        response = client.post(
            "/runs", json={"mode": "stub"}, headers={"Idempotency-Key": "same"}
        )
        assert response.status_code == 202
        run_id = response.json()["run_id"]
        state = finished(client, run_id)
        assert state["status"] == "CONSENSUS"
        assert (
            client.post(
                "/runs", json={"mode": "stub"}, headers={"Idempotency-Key": "same"}
            ).json()["run_id"]
            == run_id
        )
        assert (
            client.post(
                "/runs", json={"mode": "fallback"}, headers={"Idempotency-Key": "same"}
            ).status_code
            == 409
        )
        events = client.get(f"/runs/{run_id}/events").json()
        exported = client.get(f"/runs/{run_id}/events?format=jsonl")
        assert exported.status_code == 200
        assert [json.loads(line) for line in exported.text.splitlines()] == events
        assert [e["sequence"] for e in events] == list(range(1, len(events) + 1))
        assert client.get("/runs/not-a-run").status_code == 404
        assert client.post("/runs", json={}).status_code == 422
        assert (
            client.post(
                "/runs",
                json={"round_timeout_seconds": 0},
                headers={"Idempotency-Key": "invalid"},
            ).status_code
            == 422
        )
    with TestClient(create_app(database)) as client:
        assert client.get(f"/runs/{run_id}").json()["status"] == "CONSENSUS"
        assert (
            client.post(
                "/runs", json={"mode": "stub"}, headers={"Idempotency-Key": "same"}
            ).json()["created"]
            is False
        )
