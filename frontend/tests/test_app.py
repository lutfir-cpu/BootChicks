import json
from pathlib import Path
from types import SimpleNamespace

import pytest

AppTest = pytest.importorskip("streamlit.testing.v1").AppTest

APP = Path(__file__).resolve().parents[1] / "app.py"


def test_web_replay_and_rerun_does_not_call_agents_again(monkeypatch):
    import agents

    calls = []
    original = agents.SimulatedAgents.evaluate

    def counted(self, *args):
        calls.append(args[0])
        return original(self, *args)

    monkeypatch.setattr(agents.SimulatedAgents, "evaluate", counted)
    app = AppTest.from_file(str(APP)).run(timeout=20)
    assert not app.exception
    app.button(key="run").click().run(timeout=20)
    assert not app.exception
    assert app.session_state["result"].status == "Agreed"
    assert len(calls) == 6
    app.run()
    assert len(calls) == 6
    app.number_input[1].set_value(11).run()
    assert len(calls) == 6
    assert any("Inputs changed" in warning.value for warning in app.warning)
    assert app.session_state["result"].status == "Agreed"


def test_failure_scenarios_through_interface():
    app = AppTest.from_file(str(APP)).run(timeout=20)
    for name in ("Insufficient fuel", "No compatible gate"):
        app.selectbox[0].select(name).run()
        app.button(key="run").click().run(timeout=20)
        assert not app.exception
        assert app.session_state["result"].status == "No feasible plan"


def test_live_mode_without_credentials_is_clear(monkeypatch):
    monkeypatch.setattr("dotenv.load_dotenv", lambda *args, **kwargs: False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    app = AppTest.from_file(str(APP)).run(timeout=20)
    app.radio[0].set_value("Claude agents").run()
    assert not app.exception
    assert app.button(key="run").disabled
    assert any("ANTHROPIC_API_KEY" in warning.value for warning in app.warning)


def test_scenario_download_contains_current_edits(monkeypatch):
    from streamlit.delta_generator import DeltaGenerator

    original = DeltaGenerator.download_button
    downloads = {}

    def capture(self, label, data, *args, **kwargs):
        downloads[label] = data
        return original(self, label, data, *args, **kwargs)

    monkeypatch.setattr(DeltaGenerator, "download_button", capture)
    app = AppTest.from_file(str(APP)).run(timeout=20)
    app.text_input[0].set_value("EDITED-FLIGHT").run()
    assert not app.exception
    assert (
        json.loads(downloads["Download scenario JSON"])["flight_id"] == "EDITED-FLIGHT"
    )


def fake_anthropic(monkeypatch):
    """Accept every candidate and record the system prompt each role call receives."""
    import anthropic

    from models import AgentResponse

    systems = {}

    def parse(**kwargs):
        payload = json.loads(kwargs["messages"][0]["content"])
        systems[payload["role"]] = kwargs["system"]
        candidate = payload["candidate"]
        return SimpleNamespace(
            parsed_output=AgentResponse(
                role=payload["role"],
                candidate_id=candidate["id"],
                candidate_version=candidate["version"],
                state_version=candidate["state_version"],
                decision="ACCEPT",
                failed_rule_ids=[],
                explanation="Role check passed.",
            )
        )

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(
        anthropic,
        "Anthropic",
        lambda **kwargs: SimpleNamespace(messages=SimpleNamespace(parse=parse)),
    )
    return systems


def test_prompt_edit_and_reset_to_default():
    from prompts import DEFAULT_PROMPTS

    app = AppTest.from_file(str(APP)).run(timeout=20)
    for role in ("ATC", "Pilot", "Ground"):
        assert app.text_area(key=f"prompt_{role}").value == DEFAULT_PROMPTS[role]
        assert app.button(key=f"reset_{role}").disabled
    app.text_area(key="prompt_Pilot").input("Always prefer the shortest hold.").run()
    assert not app.exception
    assert not app.button(key="reset_Pilot").disabled
    assert app.button(key="reset_ATC").disabled
    assert any("Edited" in caption.value for caption in app.caption)
    app.button(key="reset_Pilot").click().run()
    assert not app.exception
    assert app.text_area(key="prompt_Pilot").value == DEFAULT_PROMPTS["Pilot"]
    assert app.button(key="reset_Pilot").disabled


def test_edited_prompt_is_sent_to_claude_and_recorded(monkeypatch):
    from prompts import DEFAULT_PROMPTS

    systems = fake_anthropic(monkeypatch)
    app = AppTest.from_file(str(APP)).run(timeout=20)
    app.radio(key="agent_mode").set_value("Claude agents").run()
    app.text_area(key="prompt_Ground").input("Custom ground instructions.").run()
    app.button(key="run").click().run(timeout=20)
    assert not app.exception
    assert systems["Ground"] == "Custom ground instructions."
    assert systems["ATC"] == DEFAULT_PROMPTS["ATC"]
    result = app.session_state["result"]
    assert result.system_prompts["Ground"] == "Custom ground instructions."
    assert any("Edited system prompts used for: Ground" in c.value for c in app.caption)
    app.button(key="reset_Ground").click().run()
    assert any("Inputs changed" in warning.value for warning in app.warning)


def test_blank_prompt_blocks_claude_run(monkeypatch):
    fake_anthropic(monkeypatch)
    app = AppTest.from_file(str(APP)).run(timeout=20)
    app.radio(key="agent_mode").set_value("Claude agents").run()
    app.text_area(key="prompt_ATC").input("   ").run()
    assert not app.exception
    assert app.button(key="run").disabled
    assert any("System prompt is empty for: ATC" in e.value for e in app.error)
    app.radio(key="agent_mode").set_value("Offline simulation").run()
    assert not app.button(key="run").disabled


def test_offline_results_ignore_prompt_edits():
    app = AppTest.from_file(str(APP)).run(timeout=20)
    app.button(key="run").click().run(timeout=20)
    app.text_area(key="prompt_ATC").input("Different instructions.").run()
    assert not app.exception
    assert not any("Inputs changed" in warning.value for warning in app.warning)
    assert app.session_state["result"].system_prompts == {}
