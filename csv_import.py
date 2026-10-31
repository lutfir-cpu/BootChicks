"""Chunked flight metadata import. Historical delays are not operational state."""

import io
import math

import pandas as pd

ALIASES = {
    "FLIGHT_ID": ("FLIGHT_ID", "FLIGHT_NUMBER", "FL_NUM", "OP_CARRIER_FL_NUM"),
    "ORIGIN": ("ORIGIN", "ORIGIN_AIRPORT"),
    "DESTINATION": ("DESTINATION", "DESTINATION_AIRPORT", "DEST"),
    "AIRLINE": ("AIRLINE", "OP_UNIQUE_CARRIER", "OP_CARRIER"),
    "DATE": ("FL_DATE", "DATE"),
    "WEATHER_DELAY": ("WEATHER_DELAY", "WEATHERDELAY"),
    "LATE_AIRCRAFT_DELAY": ("LATE_AIRCRAFT_DELAY", "LATEAIRCRAFTDELAY"),
}


def normalize(name):
    return str(name).strip().upper().replace(" ", "_")


def eligible_flights(data: bytes, limit: int = 200) -> list[dict]:
    if not data.strip():
        raise ValueError("The CSV is empty. Choose a flight-delay CSV.")
    selected = []
    try:
        for chunk in pd.read_csv(
            io.BytesIO(data), chunksize=50_000, dtype=str, encoding="utf-8-sig"
        ):
            names = [normalize(c) for c in chunk.columns]
            if len(names) != len(set(names)):
                raise ValueError("CSV column names must be unique after normalization.")
            chunk.columns = names
            mapping = {
                canonical: next((name for name in aliases if name in names), None)
                for canonical, aliases in ALIASES.items()
            }
            if not mapping["WEATHER_DELAY"] or not mapping["LATE_AIRCRAFT_DELAY"]:
                raise ValueError(
                    "CSV needs WEATHER_DELAY and LATE_AIRCRAFT_DELAY columns (BTS camel-case aliases also supported)."
                )
            weather = pd.to_numeric(chunk[mapping["WEATHER_DELAY"]], errors="coerce")
            late = pd.to_numeric(chunk[mapping["LATE_AIRCRAFT_DELAY"]], errors="coerce")
            # Infinity is malformed data, not an eligible delay.
            mask = (
                (weather > 15) & weather.map(lambda v: pd.notna(v) and math.isfinite(v))
            ) | ((late > 20) & late.map(lambda v: pd.notna(v) and math.isfinite(v)))
            for index, row in chunk[mask].iterrows():
                item = {
                    canonical: (str(row[name]) if pd.notna(row[name]) else None)
                    for canonical, name in mapping.items()
                    if name
                }
                item["SOURCE_ROW"] = int(index) + 2
                selected.append(item)
                if len(selected) >= limit:
                    return selected
    except (pd.errors.ParserError, pd.errors.EmptyDataError, UnicodeError) as exc:
        raise ValueError(
            "Cannot parse this file as a UTF-8 comma-separated flight CSV."
        ) from exc
    return selected
