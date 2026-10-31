import json
from pathlib import Path

from streamlit.testing.v1 import AppTest

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
    app.button[0].click().run(timeout=20)
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
        app.button[0].click().run(timeout=20)
        assert not app.exception
        assert app.session_state["result"].status == "No feasible plan"


def test_live_mode_without_credentials_is_clear(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    app = AppTest.from_file(str(APP)).run(timeout=20)
    app.radio[0].set_value("Claude agents").run()
    assert not app.exception
    assert app.button[0].disabled
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
