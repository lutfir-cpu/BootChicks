"""Streaming original three-table ingestion, exact provenance and UTC normalization."""

import csv
import hashlib
from collections import Counter
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from .schemas import (
    NormalizedFlight,
    Provenance,
    RawAirline,
    RawAirport,
    RawFlight,
    WorkflowInput,
)

FLIGHT_HEADERS = tuple(RawFlight.model_fields)
AIRLINE_HEADERS = tuple(RawAirline.model_fields)
AIRPORT_HEADERS = tuple(RawAirport.model_fields)
STRING_FLIGHT_FIELDS = {
    "AIRLINE",
    "FLIGHT_NUMBER",
    "TAIL_NUMBER",
    "ORIGIN_AIRPORT",
    "DESTINATION_AIRPORT",
    "CANCELLATION_REASON",
}
TIME_FIELDS = {
    "SCHEDULED_DEPARTURE",
    "DEPARTURE_TIME",
    "WHEELS_OFF",
    "WHEELS_ON",
    "SCHEDULED_ARRIVAL",
    "ARRIVAL_TIME",
}
# Explicit scenario configuration; never inferred from coordinates or airport prefixes.
TIMEZONES = {
    "DFW": "America/Chicago",
    "DAL": "America/Chicago",
    "ATL": "America/New_York",
    "LAX": "America/Los_Angeles",
    "SFO": "America/Los_Angeles",
    "SEA": "America/Los_Angeles",
    "ORD": "America/Chicago",
    "JFK": "America/New_York",
    "BOS": "America/New_York",
    "DEN": "America/Denver",
    "PHX": "America/Phoenix",
    "IAH": "America/Chicago",
    "DTW": "America/Detroit",
    "MIA": "America/New_York",
    "ANC": "America/Anchorage",
    "PDX": "America/Los_Angeles",
    "LAS": "America/Los_Angeles",
    "MSP": "America/Chicago",
}


def hhmm(value: int) -> tuple[int, int, int]:
    if value == 2400:
        return 0, 0, 1
    if value < 0 or value // 100 > 23 or value % 100 > 59:
        raise ValueError("INVALID_HHMM")
    return value // 100, value % 100, 0


def local_to_utc(day: date, value: int, zone: str) -> datetime:
    hour, minute, carry = hhmm(value)
    naive = datetime.combine(day + timedelta(days=carry), time(hour, minute))
    tz = ZoneInfo(zone)
    possible = set()
    for fold in (0, 1):
        aware = naive.replace(tzinfo=tz, fold=fold)
        utc = aware.astimezone(timezone.utc)
        if utc.astimezone(tz).replace(tzinfo=None) == naive:
            possible.add(utc)
    if len(possible) != 1:
        raise ValueError("AMBIGUOUS_OR_NONEXISTENT_LOCAL_TIME")
    return possible.pop()


def parse_flight(raw: dict[str, str]) -> RawFlight:
    if tuple(raw) != FLIGHT_HEADERS:
        raise ValueError("FLIGHT_HEADERS_MISMATCH")
    data = {
        key: (
            value
            if key in STRING_FLIGHT_FIELDS and value != ""
            else None
            if value.strip() == ""
            else value
        )
        for key, value in raw.items()
    }
    flight = RawFlight.model_validate(data)
    for key in TIME_FIELDS:
        if getattr(flight, key) is not None:
            hhmm(getattr(flight, key))
    return flight


def eligible(flight: RawFlight) -> bool:
    return (flight.WEATHER_DELAY is not None and flight.WEATHER_DELAY > 15) or (
        flight.LATE_AIRCRAFT_DELAY is not None and flight.LATE_AIRCRAFT_DELAY > 20
    )


def normalize(trigger: WorkflowInput) -> NormalizedFlight:
    f = trigger.flight_row
    if not eligible(f) or f.CANCELLED != 0 or f.DIVERTED != 0:
        raise ValueError("INELIGIBLE_DEMO_ROW")
    if trigger.airline_row.IATA_CODE != f.AIRLINE:
        raise ValueError("AIRLINE_LOOKUP_MISMATCH")
    airports = {a.IATA_CODE: a for a in trigger.airport_rows}
    if len(airports) != 2 or set(airports) != {f.ORIGIN_AIRPORT, f.DESTINATION_AIRPORT}:
        raise ValueError("AIRPORT_LOOKUP_MISMATCH")
    if f.ORIGIN_AIRPORT not in TIMEZONES or f.DESTINATION_AIRPORT not in TIMEZONES:
        raise ValueError("NO_TIMEZONE_PROFILE")
    for key in TIME_FIELDS:
        if getattr(f, key) is not None:
            hhmm(getattr(f, key))
    if f.SCHEDULED_TIME <= 0:
        raise ValueError("INVALID_SCHEDULED_DURATION")
    day = date(f.YEAR, f.MONTH, f.DAY)
    departure = local_to_utc(day, f.SCHEDULED_DEPARTURE, TIMEZONES[f.ORIGIN_AIRPORT])
    arrival = departure + timedelta(minutes=f.SCHEDULED_TIME)
    local_arrival = arrival.astimezone(ZoneInfo(TIMEZONES[f.DESTINATION_AIRPORT]))
    hour, minute, carry = hhmm(f.SCHEDULED_ARRIVAL)
    if (local_arrival.hour, local_arrival.minute, local_arrival.second) != (
        hour,
        minute,
        0,
    ):
        raise ValueError("SCHEDULED_ARRIVAL_DISAGREEMENT")
    if carry and local_arrival.date() != day + timedelta(days=1):
        raise ValueError("MIDNIGHT_DATE_DISAGREEMENT")
    # Check arrival's local clock is also unambiguous; never pick a DST fold implicitly.
    if (
        local_to_utc(
            local_arrival.date(), hour * 100 + minute, TIMEZONES[f.DESTINATION_AIRPORT]
        )
        != arrival
    ):
        raise ValueError("AMBIGUOUS_ARRIVAL_TIME")
    delay = max(f.WEATHER_DELAY or 0, f.LATE_AIRCRAFT_DELAY or 0, 0)
    gate_eta = arrival + timedelta(minutes=delay)
    return NormalizedFlight(
        flight_id=f"{f.AIRLINE}-{f.FLIGHT_NUMBER}-{day.isoformat()}",
        airline_code=f.AIRLINE,
        airline_name=trigger.airline_row.AIRLINE,
        tail_number=f.TAIL_NUMBER,
        origin_airport=f.ORIGIN_AIRPORT,
        destination_airport=f.DESTINATION_AIRPORT,
        scheduled_departure=departure,
        scheduled_gate_arrival=arrival,
        simulated_gate_eta=gate_eta,
        earliest_touchdown=gate_eta - timedelta(minutes=8),
        replay_mapping="Scheduled gate arrival + max(weather delay, late-aircraft delay, 0); 8 min assumed taxi. Historical actual outcomes are excluded.",
    )


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def lookup_table(path: Path, headers, model):
    typed, exact = {}, {}
    with path.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != headers:
            raise ValueError(f"{path.name.upper()}_HEADERS_MISMATCH")
        for row in reader:
            item = model.model_validate(row)
            if item.IATA_CODE in typed:
                raise ValueError("DUPLICATE_LOOKUP_KEY")
            typed[item.IATA_CODE], exact[item.IATA_CODE] = item, row
    return typed, exact


def select_row(directory: Path, mode="stub") -> WorkflowInput:
    airlines, airline_raw = lookup_table(
        directory / "airlines.csv", AIRLINE_HEADERS, RawAirline
    )
    airports, airport_raw = lookup_table(
        directory / "airports.csv", AIRPORT_HEADERS, RawAirport
    )
    hashes = {
        name: file_hash(directory / name)
        for name in ("flights.csv", "airlines.csv", "airports.csv")
    }
    rejected = Counter()
    with (directory / "flights.csv").open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != FLIGHT_HEADERS:
            raise ValueError("FLIGHT_HEADERS_MISMATCH")
        for row in reader:
            try:
                f = parse_flight(row)
                if not eligible(f):
                    continue
                if f.DESTINATION_AIRPORT != "DFW" or "DAL" not in airports:
                    rejected["NO_DESTINATION_OR_ALTERNATE_PROFILE"] += 1
                    continue
                if f.AIRLINE not in airlines or any(
                    code not in airports
                    for code in (f.ORIGIN_AIRPORT, f.DESTINATION_AIRPORT)
                ):
                    raise ValueError("UNRESOLVED_LOOKUP_KEY")
                provenance = Provenance(
                    source_type="historical_csv",
                    file_sha256=hashes,
                    source_url="https://www.kaggle.com/datasets/usdot/flight-delays",
                    csv_line=reader.line_num,
                    raw_flight=row,
                    raw_lookups={
                        "airline": airline_raw[f.AIRLINE],
                        "origin": airport_raw[f.ORIGIN_AIRPORT],
                        "destination": airport_raw[f.DESTINATION_AIRPORT],
                        "alternate": airport_raw["DAL"],
                    },
                    skipped_reasons=dict(rejected),
                )
                trigger = WorkflowInput(
                    flight_row=f,
                    airline_row=airlines[f.AIRLINE],
                    airport_rows=(
                        airports[f.ORIGIN_AIRPORT],
                        airports[f.DESTINATION_AIRPORT],
                    ),
                    mode=mode,
                    provenance=provenance,
                )
                normalize(trigger)
                return trigger
            except ValueError as exc:
                rejected[str(exc).splitlines()[0][:100]] += 1
    raise ValueError("NO_SUPPORTED_DEMO_ROW: " + str(dict(rejected)))
