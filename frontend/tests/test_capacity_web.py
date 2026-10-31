import pytest


def test_gate_schedule_validation_and_boundaries():
    from web_inputs import scheduled_gates

    gates = [{"id": "G1", "compatible": True, "handling_available": True}]
    rows = [
        {"gate_id": "G1", "start_min": 0, "end_min": 28},
        {"gate_id": "G1", "start_min": 28, "end_min": 40},
    ]
    result = scheduled_gates(gates, rows, "DFW")
    assert [(i["start"], i["end"]) for i in result[0]["occupied"]] == [
        (0, 28),
        (28, 40),
    ]
    for invalid in (
        [{"gate_id": "unknown", "start_min": 0, "end_min": 30}],
        [{"gate_id": "G1", "start_min": 0, "end_min": 0}],
        [
            {"gate_id": "G1", "start_min": 0, "end_min": 30},
            {"gate_id": "G1", "start_min": 29, "end_min": 40},
        ],
    ):
        with pytest.raises(ValueError):
            scheduled_gates(gates, invalid, "DFW")


@pytest.mark.parametrize(
    ("row", "message"),
    [
        (
            {"gate_id": "G1", "start_min": 0, "end_min": 0},
            "Busy period 1, Occupied until (min): Input should be greater than 0",
        ),
        (
            {"gate_id": "G1", "start_min": 50, "end_min": 40},
            "Busy period 1: Gate occupancy must end after it starts.",
        ),
    ],
)
def test_gate_schedule_errors_name_the_row_and_control(row, message):
    from web_inputs import scheduled_gates

    gates = [{"id": "G1", "compatible": True, "handling_available": True}]
    with pytest.raises(ValueError) as error:
        scheduled_gates(gates, [row], "DFW")
    assert str(error.value) == message


def test_web_capacity_and_gate_controls_change_real_decisions(tmp_path, monkeypatch):
    from pathlib import Path

    AppTest = pytest.importorskip("streamlit.testing.v1").AppTest
    monkeypatch.setenv("BOOTCHICKS_DATABASE", str(tmp_path / "web.sqlite"))
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py")).run(
        timeout=20
    )
    assert not app.exception
    assert app.selectbox(key="capacity_airport").value == "DFW"
    app.button(key="add_busy_period").click().run()
    until = [
        field for field in app.number_input if field.label == "Occupied until (min)"
    ]
    assert len(until) == 2
    until[1].set_value(120).run()
    app.button(key="run").click().run(timeout=20)
    result = app.session_state["result"]
    assert result.status == "No feasible plan"
    assert result.scenario.airport_capacity.min_turnaround_min == 45
    assert result.scenario.gates[1].occupied[0].end == 120
    until = [
        field for field in app.number_input if field.label == "Occupied until (min)"
    ]
    until[0].set_value(28).run()
    assert app.session_state["result"] == result
    assert any("Inputs changed" in warning.value for warning in app.warning)
    app.button(key="run").click().run(timeout=20)
    assert app.session_state["result"].status == "Agreed"
    assert app.session_state["result"].plan.gate_id == "G1"
    assert app.session_state["result"].round_count == 1
    app.selectbox(key="capacity_airport").select("DAL").run()
    assert not app.exception
    turnaround = next(
        field
        for field in app.number_input
        if field.label == "Gate occupancy duration (min)"
    )
    assert turnaround.value == 35
