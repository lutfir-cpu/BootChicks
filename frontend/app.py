"""Run from this folder with: streamlit run app.py"""

import hashlib
import json
import os
from pathlib import Path

import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from pydantic import ValidationError

from agents import ClaudeAgents, SimulatedAgents
from csv_import import eligible_flights
from engine import negotiate
from models import ROLES, Scenario
from prompts import DEFAULT_PROMPTS, resolve_prompts
from samples import bundled_scenarios

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT.parent / ".env")
st.set_page_config(
    page_title="Arrival desk", page_icon=":material/connecting_airports:", layout="wide"
)


def intervals_text(intervals):
    return ", ".join(f"{i.start}:{i.end}" for i in intervals)


def parse_intervals(value):
    if value is None or str(value).strip() == "":
        return []
    result = []
    for part in str(value).split(","):
        start, finish = part.strip().split(":")
        result.append({"start": int(start), "end": int(finish)})
    return result


def reset_prompt(role):
    st.session_state[f"prompt_{role}"] = DEFAULT_PROMPTS[role]


@st.cache_data(show_spinner=False)
def import_rows(payload):
    return eligible_flights(payload)


st.title("Arrival desk")
st.write("Three perspectives. One checkable arrival plan.")
st.caption(
    "Hackathon simulation - one arriving flight, fixed background traffic, no live operational feeds."
)
st.caption(
    "Earlier Streamlit demo. The blueprint's proposal-board negotiation is available through the BootChicks CLI and API; see README.md."
)

with st.sidebar:
    st.header("Start a replay")
    cases = bundled_scenarios()
    selection = st.selectbox("Scenario", list(cases), key="scenario_choice")
    mode = st.radio(
        "Agent mode", ["Offline simulation", "Claude agents"], key="agent_mode"
    )
    if mode == "Offline simulation":
        st.caption(
            "Offline mode uses deterministic role simulators. It does not demonstrate real LLM negotiation."
        )
    max_rounds = st.number_input(
        "Maximum negotiation rounds", min_value=1, max_value=3, value=2, step=1
    )
    st.caption(
        "One round = one candidate + three role responses + agreement check. Default: two rounds."
    )
    if mode == "Claude agents":
        st.caption(f"Model: {os.getenv('ANTHROPIC_MODEL', 'claude-sonnet-5-5')}")
        if not os.getenv("ANTHROPIC_API_KEY"):
            st.warning(
                "Set ANTHROPIC_API_KEY in your local .env file, then restart the app."
            )
    st.divider()
    st.download_button(
        "Download sample flight CSV",
        (ROOT / "data/sample_flights.csv").read_bytes(),
        file_name="sample_flights.csv",
        mime="text/csv",
    )
    scenario_download = st.empty()

template = cases[selection]
with st.expander("Import flight data or a saved scenario"):
    st.caption(
        "Historical records seed a hypothetical disruption. They do not establish fuel, runway closures or gate availability."
    )
    flight_csv = st.file_uploader("Flight-delay CSV", type=["csv"], key="csv_upload")
    if flight_csv is not None:
        try:
            rows = import_rows(flight_csv.getvalue())
            st.caption(
                "Showing up to the first 200 rows where weather delay > 15 or late-aircraft delay > 20 minutes."
            )
            if rows:
                row_index = st.selectbox(
                    "Eligible flight",
                    range(len(rows)),
                    format_func=lambda i: (
                        f"{rows[i].get('FLIGHT_ID', '?')} | {rows[i].get('ORIGIN', '?')} to {rows[i].get('DESTINATION', '?')} | CSV row {rows[i]['SOURCE_ROW']}"
                    ),
                )
                row = rows[row_index]
                st.dataframe(pd.DataFrame([row]), hide_index=True, width="stretch")
                data = template.model_dump(mode="json")
                data["flight_id"] = (
                    f"{row.get('AIRLINE') or 'FLIGHT'}-{row.get('FLIGHT_ID') or row['SOURCE_ROW']}"
                )
                data["flight_metadata"] = row
                data["provenance"]["flight_metadata"] = (
                    "Imported CSV; operational conditions remain assumed"
                )
                template = Scenario.model_validate(data)
            else:
                st.info(
                    "No eligible rows found. The bundled scenario remains selected."
                )
        except ValueError as exc:
            st.error(str(exc))
    scenario_json = st.file_uploader(
        "Scenario JSON (takes precedence over CSV metadata)",
        type=["json"],
        key="json_upload",
    )
    if scenario_json is not None:
        try:
            template = Scenario.model_validate_json(scenario_json.getvalue())
        except (ValidationError, ValueError):
            st.error(
                "Scenario JSON is invalid. Check field names, positive durations, unique resource IDs and interval end times."
            )
            st.stop()

prefix = hashlib.sha256(template.model_dump_json().encode()).hexdigest()[:12]
st.subheader("Scenario assumptions")
st.caption(
    "All times are minutes after replay start. Intervals use start:end; separate multiple intervals with commas. Endpoints do not overlap."
)
left, right = st.columns(2)
data = template.model_dump(mode="json")
with left:
    data["flight_id"] = st.text_input(
        "Flight identifier", template.flight_id, key=f"{prefix}_flight"
    )
    data["nominal_arrival_min"] = st.number_input(
        "Nominal arrival (min)",
        min_value=0,
        value=template.nominal_arrival_min,
        step=1,
        key=f"{prefix}_arrival",
    )
    data["taxi_min"] = st.number_input(
        "Taxi to gate (min)",
        min_value=0,
        value=template.taxi_min,
        step=1,
        key=f"{prefix}_taxi",
    )
    data["turnaround_min"] = st.number_input(
        "Gate occupancy duration (min)",
        min_value=1,
        value=template.turnaround_min,
        step=1,
        key=f"{prefix}_turn",
    )
with right:
    for field, label, minimum in (
        ("fuel_remaining_kg", "Fuel currently onboard (kg)", 0.0),
        ("remaining_plan_fuel_kg", "Remaining-plan fuel requirement (kg)", 0.0),
        ("fuel_buffer_kg", "Additional fuel buffer (kg)", 0.0),
        ("holding_burn_kg_min", "Holding consumption (kg/min)", 0.01),
    ):
        value = getattr(template, field)
        data[field] = st.number_input(
            label,
            min_value=minimum,
            value=float(value) if value is not None else None,
            step=1.0,
            key=f"{prefix}_{field}",
            placeholder="Unknown",
        )
    st.caption(
        "The remaining-plan requirement includes approach, landing, taxi and protected allowances after holding. Clear an input to mark it unknown."
    )

runway_rows = [
    {
        "id": r.id,
        "closed": intervals_text(r.closed),
        "reservations": intervals_text(r.reservations),
        "occupancy_min": r.occupancy_min,
        "separation_min": r.separation_min,
    }
    for r in template.runways
]
gate_rows = [
    {
        "id": g.id,
        "compatible": g.compatible,
        "occupied": intervals_text(g.occupied),
        "handling_available": g.handling_available,
    }
    for g in template.gates
]
st.markdown("**Runways - assumed**")
st.caption(
    "Separation is a simplified start-to-start gap, not a published wake-separation standard. Aircraft/runway compatibility and taxi-route availability are assumed."
)
edited_runways = st.data_editor(
    pd.DataFrame(
        runway_rows,
        columns=["id", "closed", "reservations", "occupancy_min", "separation_min"],
    ),
    hide_index=True,
    num_rows="dynamic",
    width="stretch",
    key=f"{prefix}_runways",
    column_config={
        "id": "Runway",
        "closed": "Closures (start:end)",
        "reservations": "Other traffic (start:end)",
        "occupancy_min": st.column_config.NumberColumn(
            "Occupied for (min)", min_value=1, step=1
        ),
        "separation_min": st.column_config.NumberColumn(
            "Min. gap (min)", min_value=0, step=1
        ),
    },
)
st.markdown("**Gates and ground handling - assumed**")
edited_gates = st.data_editor(
    pd.DataFrame(
        gate_rows, columns=["id", "compatible", "occupied", "handling_available"]
    ),
    hide_index=True,
    num_rows="dynamic",
    width="stretch",
    key=f"{prefix}_gates",
    column_config={
        "id": "Gate",
        "compatible": "Aircraft compatible",
        "occupied": "Occupied (start:end)",
        "handling_available": "Handling available",
    },
)
data["original_gate"] = st.text_input(
    "Original gate", template.original_gate, key=f"{prefix}_original"
)

scenario = None
try:
    data["runways"] = [
        {
            **row,
            "closed": parse_intervals(row["closed"]),
            "reservations": parse_intervals(row["reservations"]),
        }
        for row in edited_runways.to_dict("records")
    ]
    data["gates"] = [
        {**row, "occupied": parse_intervals(row["occupied"])}
        for row in edited_gates.to_dict("records")
    ]
    if not data["flight_id"].strip():
        raise ValueError("Flight identifier is required.")
    # All operational controls are editable assumptions, even when loaded from a saved replay.
    data["provenance"].update(
        {"operational_inputs": "User-editable simulation assumptions"}
    )
    scenario = Scenario.model_validate(data)
except (ValueError, TypeError):
    st.error(
        "Check scenario values: use integer start:end intervals, positive durations and unique nonempty resource IDs."
    )

with st.expander("Input sources and calculated fuel budget"):
    st.json(data["provenance"])
    if scenario and all(
        getattr(scenario, field) is not None
        for field in (
            "fuel_remaining_kg",
            "remaining_plan_fuel_kg",
            "fuel_buffer_kg",
            "holding_burn_kg_min",
        )
    ):
        budget = (
            scenario.fuel_remaining_kg
            - scenario.remaining_plan_fuel_kg
            - scenario.fuel_buffer_kg
        ) / scenario.holding_burn_kg_min
        st.write(
            f"Calculated extra holding budget: {budget:.1f} min. A negative budget means even the nominal plan fails this fuel policy."
        )

st.subheader("Agent system prompts")
st.caption(
    "Each Claude role receives its own system prompt alongside the scenario JSON. Edits apply to the next run and last for this browser session."
)
if mode != "Claude agents":
    st.caption(
        "Offline simulation uses deterministic role simulators and ignores these prompts."
    )
prompt_overrides = {}
for role, tab in zip(ROLES, st.tabs(list(ROLES), key="prompt_tabs")):
    key = f"prompt_{role}"
    st.session_state.setdefault(key, DEFAULT_PROMPTS[role])
    with tab:
        prompt_overrides[role] = st.text_area(
            f"{role} system prompt", key=key, height=340
        )
        customized = prompt_overrides[role] != DEFAULT_PROMPTS[role]
        status, reset = st.columns([4, 1], vertical_alignment="center")
        status.caption(
            "Edited - differs from the default prompt."
            if customized
            else "Using the default prompt."
        )
        reset.button(
            "Reset to default",
            key=f"reset_{role}",
            icon=":material/restart_alt:",
            on_click=reset_prompt,
            args=(role,),
            disabled=not customized,
            width="stretch",
        )
system_prompts = None
try:
    system_prompts = resolve_prompts(prompt_overrides)
except ValueError as exc:
    st.error(f"{exc} Enter instructions or reset it to the default.")

if scenario:
    scenario_download.download_button(
        "Download scenario JSON",
        scenario.model_dump_json(indent=2),
        file_name="sample_scenario.json",
        mime="application/json",
        on_click="ignore",
    )

live = mode == "Claude agents"
live_ready = not live or (
    bool(os.getenv("ANTHROPIC_API_KEY")) and system_prompts is not None
)
fingerprint = (
    hashlib.sha256(
        (
            scenario.model_dump_json()
            + mode
            + str(max_rounds)
            # Prompts only influence live runs, so offline results stay current when they change.
            + (json.dumps(system_prompts) if live else "")
        ).encode()
    ).hexdigest()
    if scenario
    else None
)
if st.button(
    "Run negotiation",
    key="run",
    type="primary",
    disabled=scenario is None or not live_ready,
):
    with st.spinner("Evaluating the arrival plan..."):
        agent = ClaudeAgents(system_prompts) if live else SimulatedAgents()
        result = negotiate(scenario, agent, int(max_rounds))
    st.session_state["result"] = result
    st.session_state["result_fingerprint"] = fingerprint

result = st.session_state.get("result")
if result:
    st.divider()
    st.subheader(result.status)
    if st.session_state.get("result_fingerprint") != fingerprint:
        st.warning(
            "Inputs changed. This result belongs to the previous scenario settings. Run again to update it."
        )
    st.write(result.reason)
    st.caption(
        f"{result.mode} | {result.round_count} rounds | {result.agent_message_count} validated agent messages | {result.api_request_count} API requests"
    )
    edited_roles = [
        role
        for role, prompt in result.system_prompts.items()
        if prompt != DEFAULT_PROMPTS[role]
    ]
    if edited_roles:
        st.caption("Edited system prompts used for: " + ", ".join(edited_roles))
    if result.missing_fields:
        st.warning("Missing: " + ", ".join(result.missing_fields))
    if result.plan:
        p = result.plan
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Plan": f"{p.id} / v{p.version}",
                        "Runway": p.runway_id,
                        "Landing (min)": p.landing_min,
                        "Gate": p.gate_id,
                        "Gate-in (min)": p.gate_in_min,
                        "Gate-out (min)": p.gate_out_min,
                    }
                ]
            ),
            hide_index=True,
            width="stretch",
        )
        with st.expander("Final mandatory checks"):
            st.dataframe(
                pd.DataFrame([c.model_dump() for c in result.final_checks]),
                hide_index=True,
                width="stretch",
            )
    for record in result.rounds:
        with st.expander(
            f"Round {record.number}: {record.candidate.id} - landing {record.candidate.landing_min}, gate {record.candidate.gate_id}",
            expanded=True,
        ):
            for response in record.responses:
                st.markdown(f"**{response.role}: {response.decision}**")
                st.write(response.explanation)
                if response.failed_rule_ids:
                    st.caption("Failed rules: " + ", ".join(response.failed_rule_ids))
                if response.proposed_changes:
                    change = response.proposed_changes
                    parts = []
                    if change.landing_min is not None:
                        parts.append(f"land at minute {change.landing_min}")
                    if change.runway_id is not None:
                        parts.append(f"runway {change.runway_id}")
                    if change.gate_id is not None:
                        parts.append(f"gate {change.gate_id}")
                    st.write("Counterproposal: " + "; ".join(parts))
            for error in record.errors:
                st.error(error)
            with st.expander("Candidate and validation details"):
                st.json(record.candidate.model_dump())
                st.dataframe(
                    pd.DataFrame([c.model_dump() for c in record.checks]),
                    hide_index=True,
                    width="stretch",
                )
    st.download_button(
        "Download replay and decisions",
        result.model_dump_json(indent=2),
        file_name="arrival_replay.json",
        mime="application/json",
        on_click="ignore",
    )
else:
    st.info(
        "Ready to replay. The default scenario needs a gate change after a runway closure."
    )
