import csv
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from bootchicks.ingestion import (
    AIRLINE_HEADERS,
    AIRPORT_HEADERS,
    FLIGHT_HEADERS,
    eligible,
    hhmm,
    local_to_utc,
    normalize,
    parse_flight,
    select_row,
)
from bootchicks.scenario import load_snapshot
from bootchicks.schemas import RawAirport, WorkflowInput

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def trigger():
    return WorkflowInput.model_validate_json(
        (ROOT / "data/fixtures/real_trigger.json").read_bytes()
    )


def test_genuine_preserved_row_and_safe_normalization(trigger):
    assert trigger.provenance.source_type == "historical_csv"
    assert tuple(trigger.provenance.raw_flight) == FLIGHT_HEADERS
    assert parse_flight(trigger.provenance.raw_flight) == trigger.flight_row
    assert eligible(trigger.flight_row)
    assert set(trigger.provenance.file_sha256) == {
        "flights.csv",
        "airlines.csv",
        "airports.csv",
    }
    assert all(len(h) == 64 for h in trigger.provenance.file_sha256.values())
    flight = normalize(trigger)
    assert flight.airline_code == "UA"
    assert flight.airline_name == "United Air Lines Inc."
    assert flight.tail_number == "N13750"
    assert flight.earliest_touchdown.date() > flight.scheduled_gate_arrival.date()
    snapshot = load_snapshot(trigger.scenario_id, trigger)
    assert snapshot.aircraft.mapping_source == "scenario_override"
    assert snapshot.aircraft.tail_number == flight.tail_number
    assert snapshot.destination.iata_code == "DFW"
    assert snapshot.alternates[0].lookup.IATA_CODE == "DAL"


@pytest.mark.parametrize(
    "weather,late,expected",
    [(15, 20, False), (15.01, None, True), (None, 20.01, True), (None, None, False)],
)
def test_strict_thresholds(trigger, weather, late, expected):
    assert (
        eligible(
            trigger.flight_row.model_copy(
                update={"WEATHER_DELAY": weather, "LATE_AIRCRAFT_DELAY": late}
            )
        )
        == expected
    )


@pytest.mark.parametrize(
    "value,expected", [(5, (0, 5, 0)), (1430, (14, 30, 0)), (2400, (0, 0, 1))]
)
def test_hhmm(value, expected):
    assert hhmm(value) == expected


@pytest.mark.parametrize("value", [-1, 1260, 2401, 2500])
def test_invalid_clock(value):
    with pytest.raises(ValueError):
        hhmm(value)


def test_midnight_rollover():
    result = local_to_utc(date(2015, 1, 1), 2400, "America/Chicago")
    assert result == datetime(2015, 1, 2, 6, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    "day,value", [(date(2026, 11, 1), 130), (date(2026, 3, 8), 230)]
)
def test_ambiguous_and_nonexistent_dst(day, value):
    with pytest.raises(ValueError, match="AMBIGUOUS"):
        local_to_utc(day, value, "America/New_York")


def test_blank_unknown_negative_and_nonfinite(trigger):
    row = dict(trigger.provenance.raw_flight)
    row["TAXI_IN"] = ""
    row["ARRIVAL_DELAY"] = "-5"
    flight = parse_flight(row)
    assert flight.TAXI_IN is None and flight.ARRIVAL_DELAY == -5
    for bad in ["NaN", "inf", "-inf"]:
        with pytest.raises(ValidationError):
            parse_flight({**row, "WEATHER_DELAY": bad})


@pytest.mark.parametrize(
    "updates", [{"CANCELLED": 1}, {"DIVERTED": 1}, {"SCHEDULED_ARRIVAL": 1234}]
)
def test_cancelled_diverted_and_schedule_disagreement(trigger, updates):
    with pytest.raises(ValueError):
        normalize(
            trigger.model_copy(
                update={"flight_row": trigger.flight_row.model_copy(update=updates)}
            )
        )


def test_lookup_mismatch_and_no_tail_inference(trigger):
    with pytest.raises(ValueError, match="AIRLINE_LOOKUP"):
        normalize(
            trigger.model_copy(
                update={
                    "airline_row": trigger.airline_row.model_copy(
                        update={"IATA_CODE": "XX"}
                    )
                }
            )
        )
    with pytest.raises(ValueError, match="AIRPORT_LOOKUP"):
        normalize(
            trigger.model_copy(
                update={
                    "airport_rows": (trigger.airport_rows[0], trigger.airport_rows[0])
                }
            )
        )
    with pytest.raises(ValueError, match="NO_TIMEZONE"):
        f = trigger.flight_row.model_copy(update={"ORIGIN_AIRPORT": "12345"})
        a = trigger.airport_rows[0].model_copy(update={"IATA_CODE": "12345"})
        normalize(
            trigger.model_copy(
                update={"flight_row": f, "airport_rows": (a, trigger.airport_rows[1])}
            )
        )


def test_three_header_streaming_selection(tmp_path, trigger):
    def write(name, headers, rows):
        with (tmp_path / name).open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=headers)
            writer.writeheader()
            writer.writerows(rows)

    raw = trigger.provenance
    write("airlines.csv", AIRLINE_HEADERS, [raw.raw_lookups["airline"]])
    write(
        "airports.csv",
        AIRPORT_HEADERS,
        [raw.raw_lookups[k] for k in ["origin", "destination", "alternate"]],
    )
    ineligible = {**raw.raw_flight, "WEATHER_DELAY": "15", "LATE_AIRCRAFT_DELAY": "20"}
    write("flights.csv", FLIGHT_HEADERS, [ineligible, raw.raw_flight])
    selected = select_row(tmp_path)
    assert selected.provenance.csv_line == 3
    assert selected.provenance.raw_flight == raw.raw_flight
    write("flights.csv", FLIGHT_HEADERS, [ineligible])
    with pytest.raises(ValueError, match="NO_SUPPORTED_DEMO_ROW"):
        select_row(tmp_path)
    (tmp_path / "flights.csv").write_text("WEATHER_DELAY\n25\n")
    with pytest.raises(ValueError, match="HEADERS_MISMATCH"):
        select_row(tmp_path)


def test_nullable_lookup_coordinates(trigger):
    airport = RawAirport.model_validate(
        {**trigger.airport_rows[0].model_dump(), "LATITUDE": "", "LONGITUDE": ""}
    )
    assert airport.LATITUDE is None and airport.LONGITUDE is None
