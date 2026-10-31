import pytest


def test_supplied_capacity_rows_and_persistent_lookup(tmp_path):
    from bootchicks.capacity import read_capacities
    from bootchicks.store import Store

    rows = read_capacities()
    assert len(rows) == 322
    dfw = next(row for row in rows if row.iata_code == "DFW")
    assert (dfw.active_runways, dfw.gates, dfw.max_runway_ops_per_hour) == (4, 150, 90)
    assert (dfw.min_turnaround_min, dfw.spare_gates_at_any_time) == (45, 3)
    store = Store(tmp_path / "capacity.sqlite")
    assert store.airport_capacities()["DFW"] == dfw
    reopened = Store(tmp_path / "capacity.sqlite")
    assert reopened.airport_capacities()["DAL"].min_turnaround_min == 35


@pytest.mark.parametrize(
    "change", ["negative", "fraction", "blank", "duplicate", "short"]
)
def test_invalid_capacity_import_is_atomic(tmp_path, change):
    import csv

    from bootchicks.capacity import DEFAULT_CAPACITY_CSV
    from bootchicks.store import Store

    grid = list(csv.reader(DEFAULT_CAPACITY_CSV.open(newline="")))
    if change == "negative":
        grid[3][6] = "-1"
    elif change == "fraction":
        grid[3][6] = "1.5"
    elif change == "blank":
        grid[3][7] = ""
    elif change == "duplicate":
        grid.append(grid[3])
    else:
        grid[3] = grid[3][:-1]
    path = tmp_path / "invalid.csv"
    with path.open("w", newline="") as handle:
        csv.writer(handle).writerows(grid)
    store = Store(tmp_path / "capacity.sqlite")
    before = store.airport_capacities()
    with pytest.raises(ValueError):
        store.import_airport_capacities(path)
    assert store.airport_capacities() == before


def test_import_versions_do_not_overwrite_old_limits(tmp_path):
    from bootchicks.capacity import DEFAULT_CAPACITY_CSV
    from bootchicks.store import Store

    store = Store(tmp_path / "capacity.sqlite")
    original = store.airport_capacities()["DFW"]
    path = tmp_path / "new.csv"
    path.write_text(DEFAULT_CAPACITY_CSV.read_text().replace(",90,45,3", ",89,45,3"))
    version = store.import_airport_capacities(path)
    assert store.airport_capacities(version)["DFW"].max_runway_ops_per_hour == 89
    assert store.airport_capacities(original.source_version)["DFW"] == original
    with pytest.raises(ValueError, match="version"):
        store.airport_capacities("unknown-version")
