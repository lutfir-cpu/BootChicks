"""SQLite audit log, idempotent runs and atomic simulator resource commits."""

import errno
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

if os.name == "nt":
    import msvcrt
else:
    import fcntl

from .capacity import DEFAULT_CAPACITY_CSV, AirportCapacity, read_capacities
from .constraints import evaluate
from .schemas import AuditEvent, RunResult, Snapshot, digest


class IdempotencyConflict(ValueError):
    pass


class Store:
    def __init__(self, path: str | Path):
        self.path = str(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY, idem_key TEXT UNIQUE NOT NULL,
                    payload_hash TEXT NOT NULL, request_json TEXT NOT NULL,
                    status TEXT NOT NULL, result_json TEXT
                );
                CREATE TABLE IF NOT EXISTS events (
                    run_id TEXT NOT NULL, sequence INTEGER NOT NULL,
                    event_id TEXT UNIQUE NOT NULL, timestamp TEXT NOT NULL,
                    kind TEXT NOT NULL, payload TEXT NOT NULL,
                    PRIMARY KEY(run_id, sequence)
                );
                CREATE TABLE IF NOT EXISTS snapshots (
                    environment_id TEXT PRIMARY KEY, base_hash TEXT NOT NULL,
                    snapshot_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS airport_capacity (
                    source_version TEXT NOT NULL, iata_code TEXT NOT NULL,
                    row_json TEXT NOT NULL,
                    PRIMARY KEY(source_version, iata_code)
                );
            """)
        self.capacity_version = self.import_airport_capacities()

    def import_airport_capacities(self, path=DEFAULT_CAPACITY_CSV):
        rows = read_capacities(path)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.executemany(
                "INSERT OR IGNORE INTO airport_capacity VALUES (?,?,?)",
                [
                    (row.source_version, row.iata_code, row.model_dump_json())
                    for row in rows
                ],
            )
            db.commit()
        return rows[0].source_version

    def airport_capacities(self, version=None):
        version = version or self.capacity_version
        with self.connect() as db:
            rows = db.execute(
                "SELECT row_json FROM airport_capacity WHERE source_version=? ORDER BY iata_code",
                (version,),
            ).fetchall()
        if not rows:
            raise ValueError("Unknown airport capacity dataset version.")
        parsed = [AirportCapacity.model_validate_json(row[0]) for row in rows]
        return {row.iata_code: row for row in parsed}

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, isolation_level=None, timeout=0.25)
        db.row_factory = sqlite3.Row
        try:
            yield db
        finally:
            db.close()

    @contextmanager
    def process_lock(self):
        """One local runtime owns restart recovery; SQL transactions still protect every commit."""
        with open(self.path + ".lock", "a+b") as lock:
            if os.name == "nt":
                if lock.tell() == 0:
                    lock.write(b"\0")
                    lock.flush()
                lock.seek(0)
            try:
                if os.name == "nt":
                    msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                if exc.errno not in (errno.EACCES, errno.EAGAIN):
                    raise
                raise RuntimeError(
                    "This database already has a running worker. Use its API or a different database."
                ) from exc
            try:
                yield
            finally:
                if os.name == "nt":
                    lock.seek(0)
                    msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(lock, fcntl.LOCK_UN)

    def open_run(self, key, request):
        if not key or len(key) > 200:
            raise ValueError("Idempotency key must have 1 to 200 characters.")
        payload = request.model_dump(mode="json")
        fingerprint = digest(payload)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT id,payload_hash FROM runs WHERE idem_key=?", (key,)
            ).fetchone()
            if existing:
                if existing["payload_hash"] != fingerprint:
                    raise IdempotencyConflict(
                        "Idempotency key already belongs to a different request."
                    )
                return existing["id"], False
            run_id = str(uuid4())
            db.execute(
                "INSERT INTO runs VALUES (?,?,?,?,?,NULL)",
                (run_id, key, fingerprint, json.dumps(payload), "QUEUED"),
            )
            db.commit()
        return run_id, True

    def running(self, run_id):
        with self.connect() as db:
            db.execute(
                "UPDATE runs SET status='RUNNING' WHERE id=? AND status='QUEUED'",
                (run_id,),
            )

    def run(self, run_id):
        with self.connect() as db:
            row = db.execute(
                "SELECT id,status,result_json FROM runs WHERE id=?", (run_id,)
            ).fetchone()
        if row is None:
            raise KeyError(run_id)
        return {
            "run_id": row["id"],
            "status": row["status"],
            "result": json.loads(row["result_json"]) if row["result_json"] else None,
        }

    def _event(self, db, run_id, kind, payload):
        seq = db.execute(
            "SELECT COALESCE(MAX(sequence),0)+1 FROM events WHERE run_id=?", (run_id,)
        ).fetchone()[0]
        event = AuditEvent(
            event_id=str(uuid4()),
            sequence=seq,
            run_id=run_id,
            timestamp=datetime.now(timezone.utc),
            kind=kind,
            payload=payload,
        )
        db.execute(
            "INSERT INTO events VALUES (?,?,?,?,?,?)",
            (
                run_id,
                seq,
                event.event_id,
                event.timestamp.isoformat(),
                kind,
                json.dumps(payload, allow_nan=False),
            ),
        )
        return event

    def append(self, run_id, kind, payload):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            event = self._event(db, run_id, kind, payload)
            db.commit()
        return event

    def events(self, run_id):
        self.run(run_id)
        with self.connect() as db:
            rows = db.execute(
                "SELECT * FROM events WHERE run_id=? ORDER BY sequence", (run_id,)
            ).fetchall()
        return [
            AuditEvent(
                event_id=r["event_id"],
                sequence=r["sequence"],
                run_id=run_id,
                timestamp=r["timestamp"],
                kind=r["kind"],
                payload=json.loads(r["payload"]),
            )
            for r in rows
        ]

    def load_or_seed(self, initial: Snapshot) -> Snapshot:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM snapshots WHERE environment_id=?",
                (initial.environment_id,),
            ).fetchone()
            if row:
                if row["base_hash"] != digest(initial):
                    raise ValueError(
                        "SCENARIO_PROFILE_CHANGED: use a new profile version or environment."
                    )
                return Snapshot.model_validate_json(row["snapshot_json"])
            db.execute(
                "INSERT INTO snapshots VALUES (?,?,?)",
                (initial.environment_id, digest(initial), initial.model_dump_json()),
            )
            db.commit()
        return initial

    def current(self, environment_id):
        with self.connect() as db:
            row = db.execute(
                "SELECT snapshot_json FROM snapshots WHERE environment_id=?",
                (environment_id,),
            ).fetchone()
        if row is None:
            raise KeyError(environment_id)
        return Snapshot.model_validate_json(row[0])

    def finish(self, run_id, result: RunResult):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._event(
                db,
                run_id,
                "TERMINAL",
                {"status": result.status, "reason": result.terminal_reason},
            )
            db.execute(
                "UPDATE runs SET status=?,result_json=? WHERE id=?",
                (result.status, result.model_dump_json(), run_id),
            )
            db.commit()

    def fail(self, run_id, reason):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._event(db, run_id, "TERMINAL", {"status": "FAILED", "reason": reason})
            db.execute(
                "UPDATE runs SET status='FAILED',result_json=? WHERE id=?",
                (json.dumps({"terminal_reason": reason}), run_id),
            )
            db.commit()

    def recover_interrupted(self):
        with self.connect() as db:
            ids = [
                r[0]
                for r in db.execute(
                    "SELECT id FROM runs WHERE status IN ('RUNNING','QUEUED')"
                )
            ]
        for run_id in ids:
            self.fail(run_id, "INTERRUPTED_BY_RESTART")
        return ids

    def commit(self, run_id, expected: Snapshot, plan, build_result):
        """Version check, revalidation, bookings, certificate and terminal record share one transaction."""
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT snapshot_json FROM snapshots WHERE environment_id=?",
                (expected.environment_id,),
            ).fetchone()
            current = Snapshot.model_validate_json(row[0])
            if current.snapshot_version != expected.snapshot_version or digest(
                current
            ) != digest(expected):
                return None
            report = evaluate(current, plan)
            if not report.feasible:
                return None
            updated = current.model_copy(
                update={
                    "version": current.version + 1,
                    "reservations": current.reservations + report.reservations,
                }
            )
            event = self._event(
                db,
                run_id,
                "RESOURCE_COMMIT",
                {
                    "plan_hash": plan.plan_hash,
                    "snapshot_before": current.snapshot_version,
                    "snapshot_after": updated.snapshot_version,
                    "reservations": [
                        r.model_dump(mode="json") for r in report.reservations
                    ],
                },
            )
            result = build_result(report, event.event_id)
            db.execute(
                "UPDATE snapshots SET snapshot_json=? WHERE environment_id=?",
                (updated.model_dump_json(), current.environment_id),
            )
            self._event(
                db,
                run_id,
                "TERMINAL",
                {"status": result.status, "reason": result.terminal_reason},
            )
            db.execute(
                "UPDATE runs SET status=?,result_json=? WHERE id=?",
                (result.status, result.model_dump_json(), run_id),
            )
            db.commit()
            return result
