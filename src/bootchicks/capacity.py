"""Typed, versioned reference limits supplied by the challenge, never live airport data."""

import csv
import hashlib
import io
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

DEFAULT_CAPACITY_CSV = (
    Path(__file__).resolve().parents[2] / "data/constraints/airport_capacity.csv"
)
COLUMNS = (
    "IATA_CODE",
    "AIRPORT",
    "CITY",
    "STATE",
    "delayed_departures_in_flights_csv",
    "size_class",
    "active_runways",
    "gates",
    "max_runway_ops_per_hour",
    "min_turnaround_min",
    "spare_gates_at_any_time",
)
NUMERIC = COLUMNS[4:5] + COLUMNS[6:]


class AirportCapacity(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)
    iata_code: str = Field(pattern=r"^[A-Z]{3}$")
    airport: str = Field(min_length=1)
    city: str = Field(min_length=1)
    state: str = Field(min_length=1)
    delayed_departures_in_flights_csv: int = Field(ge=0, strict=True)
    size_class: str = Field(min_length=1)
    active_runways: int = Field(ge=1, strict=True)
    gates: int = Field(ge=1, strict=True)
    max_runway_ops_per_hour: int = Field(ge=1, strict=True)
    min_turnaround_min: int = Field(ge=1, strict=True)
    spare_gates_at_any_time: int = Field(ge=0, strict=True)
    source_version: str
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_kind: Literal["challenge_synthetic"] = "challenge_synthetic"

    @model_validator(mode="after")
    def spare_limit(self):
        if self.spare_gates_at_any_time > self.gates:
            raise ValueError("Spare gates cannot exceed total gates.")
        return self


def read_capacities(
    path: str | Path = DEFAULT_CAPACITY_CSV,
) -> tuple[AirportCapacity, ...]:
    payload = Path(path).read_bytes()
    source_hash = hashlib.sha256(payload).hexdigest()
    version = f"challenge-capacity-{source_hash[:16]}"
    grid = csv.reader(io.StringIO(payload.decode("utf-8-sig")), strict=True)
    for header in grid:
        if header and header[0].strip() == "IATA_CODE":
            break
    else:
        raise ValueError("Capacity CSV is missing its IATA_CODE header.")
    if tuple(cell.strip() for cell in header) != COLUMNS:
        raise ValueError("Capacity CSV columns do not match the challenge schema.")
    rows, seen = [], set()
    for cells in grid:
        if not cells or not any(cell.strip() for cell in cells):
            continue
        if len(cells) != len(COLUMNS) or any(not cell.strip() for cell in cells):
            raise ValueError(f"Incomplete capacity row at CSV line {grid.line_num}.")
        raw = dict(zip(COLUMNS, (cell.strip() for cell in cells), strict=True))
        values = {key.lower(): value for key, value in raw.items()}
        for key in NUMERIC:
            if not raw[key].isascii() or not raw[key].isdecimal():
                raise ValueError(
                    f"{key} must be a nonnegative whole number at CSV line {grid.line_num}."
                )
            values[key] = int(raw[key])
        row = AirportCapacity(
            **values, source_version=version, source_sha256=source_hash
        )
        if row.iata_code in seen:
            raise ValueError(f"Duplicate capacity airport {row.iata_code}.")
        seen.add(row.iata_code)
        rows.append(row)
    if not rows:
        raise ValueError("Capacity CSV contains no airport rows.")
    return tuple(rows)


def rolling_operations(starts, proposed_start):
    """Count modeled runway-operation starts in all affected half-open rolling hours."""
    starts = [*starts, proposed_start]
    return max(
        sum(start <= value < start + 3600 for value in starts)
        for start in starts
        if start <= proposed_start < start + 3600
    )
