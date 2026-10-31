"""API features the React frontend relies on: options, fresh environments and prompt overrides."""

import pytest
from fastapi.testclient import TestClient
from test_blueprint_api import finished

import bootchicks.negotiation
from bootchicks.api import create_app
from bootchicks.providers import (
    DEFAULT_PROMPTS,
    PROMPT_VERSION,
    StubProvider,
    prompt_identity,
    resolve_prompts,
)
from bootchicks.schemas import ROLES


def submit(client, key, **body):
    response = client.post("/runs", json=body, headers={"Idempotency-Key": key})
    assert response.status_code == 202, response.text
    return finished(client, response.json()["run_id"])


def test_options_describe_scenarios_gates_prompts_and_live_availability(
    tmp_path, monkeypatch
):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with TestClient(create_app(tmp_path / "options.sqlite")) as client:
        options = client.get("/options").json()
    assert [s["id"] for s in options["scenarios"]] == [
        "runway_closure_gate_conflict_v1",
        "insufficient_fuel",
        "no_gate",
        "diversion",
    ]
    default = options["scenarios"][0]
    assert default["preferred_gate"] == "A1"
    assert [(a["iata_code"], a["kind"], a["gates"]) for a in default["airports"]] == [
        ("DFW", "destination", ["A1", "B2", "C3", "D4"]),
        ("DAL", "alternate", ["A1", "B2", "C3", "D4"]),
    ]
    assert default["window_min"] == 120
    assert default["aircraft"]["fuel_kg"] == 6000
    assert default["airports"][0]["runways"] == [
        {"id": "R1", "closed": [{"start_min": 0, "end_min": 22}]},
        {"id": "R2", "closed": [{"start_min": 0, "end_min": 120}]},
    ]
    assert default["airports"][0]["crews"] == 3
    fuel = next(s for s in options["scenarios"] if s["id"] == "insufficient_fuel")
    assert fuel["aircraft"]["fuel_kg"] == 4300
    assert options["live_available"] is False
    assert options["default_prompts"] == DEFAULT_PROMPTS
    assert set(options["default_prompts"]) == set(ROLES)
    assert options["prompt_version"] == PROMPT_VERSION
    assert options["sample_trigger"]["provenance"]["csv_line"] == 3121

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    with TestClient(create_app(tmp_path / "options.sqlite")) as client:
        assert client.get("/options").json()["live_available"] is True


def test_named_environments_start_fresh_while_shared_state_is_kept(tmp_path):
    with TestClient(create_app(tmp_path / "env.sqlite")) as client:
        first = submit(client, "a", mode="stub", environment="ui-1")
        second = submit(client, "b", mode="stub", environment="ui-2")
        repeat = submit(client, "c", mode="stub", environment="ui-1")
        assert first["result"]["status"] == second["result"]["status"] == "CONSENSUS"
        # The same environment already holds this flight's committed resources.
        assert repeat["result"]["status"] == "ESCALATED"
        assert (
            first["result"]["snapshot_version"] != second["result"]["snapshot_version"]
        )
        invalid = client.post(
            "/runs",
            json={"environment": "has spaces"},
            headers={"Idempotency-Key": "bad-env"},
        )
        assert invalid.status_code == 422


def test_sample_trigger_runs_with_selected_scenario(tmp_path):
    with TestClient(create_app(tmp_path / "trigger.sqlite")) as client:
        trigger = client.get("/options").json()["sample_trigger"]
        state = submit(
            client,
            "trigger",
            trigger={**trigger, "scenario_id": "diversion"},
            mode="stub",
            environment="trigger",
        )
    assert state["result"]["status"] == "FALLBACK"
    assert state["result"]["source_provenance"]["source_type"] == "historical_csv"
    assert state["result"]["selected_plan"]["action"]["airport"] == "DAL"


def test_live_runs_use_and_record_edited_prompts(tmp_path, monkeypatch):
    created = []

    class FakeClaude(StubProvider):
        # Deterministic replies; only the prompt handling of the live path is under test.
        is_live = True

        def __init__(self, system_prompts=None):
            self.system_prompts = resolve_prompts(system_prompts)
            self.prompt_version = prompt_identity(self.system_prompts)
            created.append(self.system_prompts)

        async def close(self):
            pass

    monkeypatch.setattr(bootchicks.negotiation, "ClaudeProvider", FakeClaude)
    custom = {"GROUND": "Prefer the assigned gate above all else."}
    with TestClient(create_app(tmp_path / "live.sqlite")) as client:
        state = submit(
            client, "live", mode="live", environment="live", role_prompts=custom
        )
        events = client.get(f"/runs/{state['run_id']}/events").json()
    assert state["result"]["status"] == "CONSENSUS"
    assert created == [{**DEFAULT_PROMPTS, **custom}]
    round_input = next(e for e in events if e["kind"] == "ROUND_INPUT")
    assert round_input["payload"]["system_prompts"]["GROUND"] == custom["GROUND"]
    assert round_input["payload"]["system_prompts"]["ATC"] == DEFAULT_PROMPTS["ATC"]
    versions = {
        e["payload"]["prompt_version"] for e in events if e["kind"] == "AGENT_MESSAGE"
    }
    assert versions == {prompt_identity({**DEFAULT_PROMPTS, **custom})}
    assert versions.pop().startswith(f"{PROMPT_VERSION}+custom-")


def test_stub_runs_do_not_claim_prompts(tmp_path):
    with TestClient(create_app(tmp_path / "stub.sqlite")) as client:
        state = submit(
            client,
            "stub",
            mode="stub",
            role_prompts={"ATC": "Ignored by fixtures."},
        )
        events = client.get(f"/runs/{state['run_id']}/events").json()
    round_input = next(e for e in events if e["kind"] == "ROUND_INPUT")
    assert "system_prompts" not in round_input["payload"]


@pytest.mark.parametrize(
    ("prompts", "message"),
    [
        ({"ATC": "   "}, "System prompt for ATC is empty."),
        ({"PILOT": "x" * 8001}, "System prompt for PILOT exceeds 8,000 characters."),
        ({"TOWER": "x"}, "Input should be 'ATC', 'PILOT' or 'GROUND'"),
    ],
)
def test_invalid_prompts_are_rejected(tmp_path, prompts, message):
    with TestClient(create_app(tmp_path / "invalid.sqlite")) as client:
        response = client.post(
            "/runs",
            json={"mode": "live", "role_prompts": prompts},
            headers={"Idempotency-Key": "invalid"},
        )
    assert response.status_code == 422
    assert message in response.text


def test_built_frontend_is_served_without_shadowing_the_api(tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html><title>Arrival desk</title>")
    with TestClient(create_app(tmp_path / "web.sqlite", frontend_dir=dist)) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert "Arrival desk" in page.text
        assert client.get("/options").json()["scenarios"]
    with TestClient(create_app(tmp_path / "web.sqlite")) as client:
        assert client.get("/").status_code == 404
