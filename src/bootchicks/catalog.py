"""Catalogue of real disrupted flights the simulator can replay, imported once from the Kaggle CSVs.

Scanning flights.csv takes minutes, so `import_flights` stores each supported flight's raw row once
(tables `flights` and `flight_import`, created by `Store`); the app then searches it and rebuilds the
exact, validated trigger on demand.
"""

import json
from collections import Counter
from datetime import datetime, timezone

from .ingestion import iter_triggers, parse_flight
from .schemas import Provenance, RawAirline, RawAirport, WorkflowInput


def import_flights(store, directory, progress=None):
    """Replace the catalogue with every supported disrupted flight in `directory`; returns the summary."""
    stats, rejected, rows = Counter(), Counter(), []
    hashes = None
    for trigger in iter_triggers(directory, stats=stats, rejected=rejected):
        f, p = trigger.flight_row, trigger.provenance
        hashes = p.file_sha256
        airline, origin = p.raw_lookups["airline"], p.raw_lookups["origin"]
        rows.append(
            (
                p.csv_line,
                f"{f.YEAR}-{f.MONTH:02d}-{f.DAY:02d}",
                f.AIRLINE,
                f.FLIGHT_NUMBER,
                f.ORIGIN_AIRPORT,
                f.DESTINATION_AIRPORT,
                f.SCHEDULED_ARRIVAL,
                round(max(f.WEATHER_DELAY or 0, f.LATE_AIRCRAFT_DELAY or 0)),
                " ".join(
                    (
                        f"{f.AIRLINE}{f.FLIGHT_NUMBER}",
                        f"{f.AIRLINE} {f.FLIGHT_NUMBER}",
                        airline["AIRLINE"],
                        f.ORIGIN_AIRPORT,
                        origin["AIRPORT"],
                        origin["CITY"],
                        f"{f.YEAR}-{f.MONTH:02d}-{f.DAY:02d}",
                    )
                ).lower(),
                json.dumps(p.raw_flight),
                json.dumps(p.raw_lookups),
            )
        )
        if progress and len(rows) % 1000 == 0:
            progress(len(rows))
    summary = {
        "imported_at": datetime.now(timezone.utc).isoformat(),
        "file_sha256": hashes or {},
        "rows": stats["rows"],
        "disrupted": stats["disrupted"],
        "supported": len(rows),
        "skipped": dict(rejected.most_common()),
    }
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("DELETE FROM flights")
        db.executemany("INSERT INTO flights VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows)
        db.execute(
            "INSERT OR REPLACE INTO flight_import VALUES (1,?,?,?,?,?,?)",
            (
                summary["imported_at"],
                json.dumps(summary["file_sha256"]),
                summary["rows"],
                summary["disrupted"],
                summary["supported"],
                json.dumps(summary["skipped"]),
            ),
        )
        db.commit()
    return summary


def import_summary(store):
    with store.connect() as db:
        row = db.execute("SELECT * FROM flight_import WHERE id = 1").fetchone()
    if row is None:
        return None
    return {
        "imported_at": row["imported_at"],
        "rows": row["rows"],
        "disrupted": row["disrupted"],
        "supported": row["supported"],
        "skipped": json.loads(row["skipped"]),
    }


def search_flights(store, query="", limit=50):
    """Flights whose airline, number, origin or date match every word of `query`, earliest first."""
    words = query.lower().split()
    where = " AND ".join("search LIKE ?" for _ in words) or "1"
    params = [f"%{word}%" for word in words]
    with store.connect() as db:
        total = db.execute(
            f"SELECT COUNT(*) FROM flights WHERE {where}", params
        ).fetchone()[0]
        rows = db.execute(
            f"SELECT * FROM flights WHERE {where} ORDER BY flight_date, scheduled_arrival LIMIT ?",
            [*params, limit],
        ).fetchall()
    return {"matches": total, "flights": [summary(row) for row in rows]}


def summary(row):
    lookups = json.loads(row["raw_lookups"])
    flight = parse_flight(json.loads(row["raw_flight"]))
    return {
        "csv_line": row["csv_line"],
        "date": row["flight_date"],
        "airline": row["airline"],
        "airline_name": lookups["airline"]["AIRLINE"],
        "flight_number": row["flight_number"],
        "origin": row["origin"],
        "origin_city": lookups["origin"]["CITY"],
        "destination": row["destination"],
        "scheduled_arrival": row["scheduled_arrival"],
        "delay_min": row["delay_min"],
        "weather_delay": flight.WEATHER_DELAY,
        "late_aircraft_delay": flight.LATE_AIRCRAFT_DELAY,
    }


def flight_trigger(store, csv_line):
    """The exact, validated trigger for one catalogued flight, or None."""
    with store.connect() as db:
        row = db.execute(
            "SELECT * FROM flights WHERE csv_line = ?", (csv_line,)
        ).fetchone()
        meta = db.execute(
            "SELECT file_sha256 FROM flight_import WHERE id = 1"
        ).fetchone()
    if row is None:
        return None
    raw = json.loads(row["raw_flight"])
    lookups = json.loads(row["raw_lookups"])
    return WorkflowInput(
        flight_row=parse_flight(raw),
        airline_row=RawAirline.model_validate(lookups["airline"]),
        airport_rows=(
            RawAirport.model_validate(lookups["origin"]),
            RawAirport.model_validate(lookups["destination"]),
        ),
        provenance=Provenance(
            source_type="historical_csv",
            source_url="https://www.kaggle.com/datasets/usdot/flight-delays",
            file_sha256=json.loads(meta["file_sha256"]),
            csv_line=csv_line,
            raw_flight=raw,
            raw_lookups=lookups,
        ),
    )
