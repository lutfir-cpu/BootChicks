import pytest

pytest.importorskip("pandas")

from csv_import import eligible_flights


def test_case_aliases_thresholds_and_metadata():
    csv = b"flight_number,origin_airport,destination_airport,weather_delay,late_aircraft_delay\n1,ATL,DFW,15,20\n2,ATL,DFW,16,0\n3,DFW,ATL,0,21\n4,ATL,DFW,,\n"
    rows = eligible_flights(csv)
    assert [row["FLIGHT_ID"] for row in rows] == ["2", "3"]
    assert rows[0]["SOURCE_ROW"] == 3
    assert rows[0]["DESTINATION"] == "DFW"


def test_bts_camelcase_and_limit():
    assert (
        len(eligible_flights(b"WeatherDelay,LateAircraftDelay\n20,0\n30,0\n", limit=1))
        == 1
    )


@pytest.mark.parametrize(
    "data",
    [b"", b"junk\nabc\n", b'WEATHER_DELAY,LATE_AIRCRAFT_DELAY\n"bad,25\n', b"\xff\xfe"],
)
def test_invalid_csv(data):
    with pytest.raises(ValueError):
        eligible_flights(data)


def test_non_numeric_delay_does_not_create_eligibility():
    assert eligible_flights(b"WEATHER_DELAY,LATE_AIRCRAFT_DELAY\ninf,0\nabc,\n") == []
