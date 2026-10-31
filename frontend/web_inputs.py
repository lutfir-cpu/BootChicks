"""Translate explicit web gate schedules into the legacy demo's interval model."""

from pydantic import ValidationError

from bootchicks.schemas import RunRequest

LABELS = {
    "gate_id": "Gate",
    "start_min": "Occupied from (min)",
    "end_min": "Occupied until (min)",
}


def scheduled_gates(gates, rows, airport):
    identifiers = [str(gate["id"]).strip() for gate in gates]
    if any(not value for value in identifiers) or len(set(identifiers)) != len(
        identifiers
    ):
        raise ValueError("Gate identifiers must be nonempty and unique.")
    try:
        schedule = RunRequest(
            gate_occupancies=[{"airport": airport, **row} for row in rows]
        ).gate_occupancies
    except ValidationError as exc:
        error = exc.errors()[0]
        message = error["msg"].removeprefix("Value error, ")
        # Locations look like ("gate_occupancies", row, field); name the row and control the user sees.
        location = error["loc"][1:]
        if location and isinstance(location[0], int):
            label = LABELS.get(location[1]) if len(location) > 1 else None
            prefix = f"Busy period {location[0] + 1}" + (f", {label}" if label else "")
            message = f"{prefix}: {message}"
        raise ValueError(message) from None
    if any(row.gate_id not in identifiers for row in schedule):
        raise ValueError(
            "A busy period refers to an unknown gate. Choose a configured gate or remove the period."
        )
    return [
        {
            **gate,
            "id": ident,
            "occupied": [
                {"start": row.start_min, "end": row.end_min}
                for row in schedule
                if row.gate_id == ident
            ],
        }
        for gate, ident in zip(gates, identifiers, strict=True)
    ]
