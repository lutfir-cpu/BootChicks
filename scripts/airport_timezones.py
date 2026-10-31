"""Regenerate data/constraints/airport_timezones.csv from the Kaggle airports.csv.

Run from the repository root: python scripts/airport_timezones.py data/raw/flight-delays/airports.csv
Each airport's IANA zone comes from its coordinates (timezonefinder, a dev dependency).
Airports with missing or wrong coordinates in airports.csv are set by hand below.
The committed CSV is what the app reads; it never infers zones at runtime.
"""

import csv
import sys
from pathlib import Path

from timezonefinder import TimezoneFinder

OUT = Path(__file__).resolve().parents[1] / "data/constraints/airport_timezones.csv"
MANUAL = {
    # No coordinates in airports.csv.
    "ECP": "America/Chicago",  # Northwest Florida Beaches, Panama City
    "PBG": "America/New_York",  # Plattsburgh, New York
    "UST": "America/New_York",  # St. Augustine, Florida
    # Coordinates in airports.csv have the wrong sign and fall in the ocean.
    "GUM": "Pacific/Guam",
    "PPG": "Pacific/Pago_Pago",
}


def main(source):
    finder = TimezoneFinder()
    rows = []
    with open(source, newline="", encoding="utf-8-sig") as stream:
        for airport in csv.DictReader(stream):
            code = airport["IATA_CODE"]
            if code in MANUAL:
                rows.append((code, MANUAL[code], "manual"))
                continue
            zone = finder.timezone_at(
                lat=float(airport["LATITUDE"]), lng=float(airport["LONGITUDE"])
            )
            if zone is None or zone.startswith("Etc/"):
                raise SystemExit(f"No timezone for {code}; add it to MANUAL.")
            rows.append((code, zone, "coordinates"))
    with OUT.open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(("IATA_CODE", "TIMEZONE", "SOURCE"))
        writer.writerows(sorted(rows))
    print(f"Wrote {len(rows)} airports to {OUT}")


if __name__ == "__main__":
    main(sys.argv[1])
