"""Importing every supported real flight once, then searching it and running any of them."""

import csv
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from bootchicks.api import create_app
from bootchicks.catalog import flight_trigger, import_flights, search_flights
from bootchicks.ingestion import (
    AIRLINE_HEADERS,
    AIRPORT_HEADERS,
    FLIGHT_HEADERS,
    TIMEZONES,
    normalize,
    select_row,
)
from bootchicks.schemas import WorkflowInput
from bootchicks.store import Store

ROOT = Path(__file__).resolve().parents[1]


def write(path, headers, rows):
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)


@pytest.fixture
def dataset(tmp_path):
    """A small copy of the three Kaggle tables: one row of each kind the import must handle."""
    sample = WorkflowInput.model_validate_json(
        (ROOT / "data/fixtures/real_trigger.json").read_bytes()
    ).provenance
    lookups = sample.raw_lookups
    austin = {
        **lookups["origin"],
        "IATA_CODE": "AUS",
        "AIRPORT": "Austin-Bergstrom International Airport",
        "CITY": "Austin",
        "STATE": "TX",
    }
    write(tmp_path / "airlines.csv", AIRLINE_HEADERS, [lookups["airline"]])
    write(
        tmp_path / "airports.csv",
        AIRPORT_HEADERS,
        [lookups["origin"], lookups["destination"], lookups["alternate"], austin],
    )
    flight = sample.raw_flight
    write(
        tmp_path / "flights.csv",
        FLIGHT_HEADERS,
        [
            {
                **flight,
                "WEATHER_DELAY": "15",
                "LATE_AIRCRAFT_DELAY": "20",
            },  # not disrupted
            flight,  # UA 1590 ORD to DFW, line 3
            {
                **flight,
                "ORIGIN_AIRPORT": "DFW",
                "DESTINATION_AIRPORT": "ORD",
            },  # no ORD profile
            # Austin was missing from the old hand-written timezone list; both are on Central time.
            {**flight, "FLIGHT_NUMBER": "2", "ORIGIN_AIRPORT": "AUS", "DAY": "2"},
            {**flight, "SCHEDULED_ARRIVAL": "9999"},  # malformed
        ],
    )
    return tmp_path


def test_import_catalogues_every_supported_disrupted_flight(tmp_path, dataset):
    store = Store(tmp_path / "catalog.sqlite")
    summary = import_flights(store, dataset)
    # The malformed row fails to parse, so it is skipped before it can count as disrupted.
    assert (summary["rows"], summary["disrupted"], summary["supported"]) == (5, 3, 2)
    assert summary["skipped"]["NO_DESTINATION_OR_ALTERNATE_PROFILE"] == 1
    assert sum(summary["skipped"].values()) == 2

    everything = search_flights(store)
    assert everything["matches"] == 2
    first = everything["flights"][0]
    assert first == {
        "csv_line": 3,
        "date": "2015-01-01",
        "airline": "UA",
        "airline_name": "United Air Lines Inc.",
        "flight_number": "1590",
        "origin": "ORD",
        "origin_city": "Chicago",
        "destination": "DFW",
        "scheduled_arrival": 1228,
        "delay_min": 467,
        "weather_delay": 0.0,
        "late_aircraft_delay": 467.0,
    }
    assert [f["origin"] for f in search_flights(store, "austin")["flights"]] == ["AUS"]
    assert search_flights(store, "UA 1590 chicago")["matches"] == 1
    assert search_flights(store, "2015-01-02")["matches"] == 1
    assert search_flights(store, "boston")["matches"] == 0

    # Rebuilt triggers are exact and valid: the same row, lookups and hashes as a direct CSV selection.
    trigger = flight_trigger(store, 3)
    selected = select_row(dataset)
    assert trigger.flight_row == selected.flight_row
    assert trigger.provenance.raw_flight == selected.provenance.raw_flight
    assert trigger.provenance.raw_lookups == selected.provenance.raw_lookups
    assert trigger.provenance.file_sha256 == selected.provenance.file_sha256
    assert normalize(flight_trigger(store, 5)).origin_airport == "AUS"
    assert flight_trigger(store, 4) is None

    # A second import replaces the catalogue rather than adding to it.
    import_flights(store, dataset)
    assert search_flights(store)["matches"] == 2


def test_api_searches_and_runs_imported_flights(tmp_path, dataset):
    database = tmp_path / "api.sqlite"
    with TestClient(create_app(database)) as client:
        empty = client.get("/flights").json()
        assert empty == {"imported": None, "matches": 0, "flights": []}
        assert client.get("/flights/3").status_code == 404

        import_flights(Store(database), dataset)
        listed = client.get("/flights", params={"q": "austin"}).json()
        assert listed["imported"]["supported"] == 2
        assert [f["csv_line"] for f in listed["flights"]] == [5]
        assert client.get("/flights", params={"limit": 0}).status_code == 422

        trigger = client.get("/flights/5").json()
        response = client.post(
            "/runs",
            json={
                "scenario_id": "runway_closure_gate_conflict_v1",
                "mode": "stub",
                "trigger": trigger,
            },
            headers={"Idempotency-Key": "austin"},
        )
        assert response.status_code == 202, response.text
        run_id = response.json()["run_id"]
        while (state := client.get(f"/runs/{run_id}").json())["status"] in (
            "QUEUED",
            "RUNNING",
        ):
            time.sleep(0.02)
        assert state["status"] == "CONSENSUS"
        assert state["result"]["source_provenance"]["csv_line"] == 5


def test_every_airport_has_an_explicit_timezone():
    with (ROOT / "data/constraints/airport_timezones.csv").open() as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 322 and len(TIMEZONES) == 322
    assert all(not r["TIMEZONE"].startswith("Etc/") for r in rows)
    assert TIMEZONES["DFW"] == TIMEZONES["DAL"] == TIMEZONES["AUS"] == "America/Chicago"
    assert TIMEZONES["ELP"] == "America/Denver"  # El Paso, Texas, keeps Mountain time.
    assert (
        TIMEZONES["GUM"] == "Pacific/Guam"
    )  # airports.csv gives Guam the wrong longitude sign.
