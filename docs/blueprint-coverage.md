# Blueprint coverage

The authoritative backend is `src/bootchicks`.
The React web app in `frontend/` is a client of this backend.

| Blueprint area | Implemented evidence |
| --- | --- |
| Genuine three-table input | `data/fixtures/real_trigger.json`: original row 3121, all raw fields/lookups, three CSV hashes; `import-flights` stores every supported disrupted row the same way |
| Time and provenance | Strict schemas, nullable numeric cells, explicit zones, UTC normalization, preserved raw outcomes excluded from agent contexts |
| Mock operational state | Versioned JSON profile, explicitly overridden aircraft mapping, units/validity labels and documented fuel floors |
| Two-round independent negotiation | Three proposal calls, deduplicated board, three complete vote calls, exact hashes and cross-domain references |
| Authoritative constraints | Runway/wake/rolling capacity/sector/taxi, fuel/weather, gates/crews/overtime, snapshot identity |
| Selection and impact | Frozen domain costs and deterministic tie breaks; same-model feasible baseline and deltas |
| Consensus | Exact three-agent vote intersection plus successful atomic resource commit and certificate |
| Fallback | Same validators, bounded destination/alternate enumeration, explicit escalation when none is feasible |
| Durability | SQLite runs/events/snapshots, single worker ownership, transactional reservations and terminal results |
| CLI/API | Streaming row selector and flight catalogue import; run/export/serve commands; flight search; idempotent HTTP 202 triggers, 409 conflicts, ordered JSONL |
| Failure boundaries | No hidden repair calls, cancellation/deadlines, missing/invalid evidence fails closed, interrupted jobs remain failed |
| Live provider | Direct pinned Anthropic async SDK; automated checks use mocked traffic, no claim of a real paid smoke test |

The blueprint's numerical worked comparison uses the standard approach: B2 at T+25 versus A1 at T+35 yields 10 fewer holding minutes, 400 kg less modeled airborne fuel, gate arrival 10 minutes earlier and eight fewer overtime minutes.
Other live proposals can yield different unanimously approved outcomes.
The baseline ties earliest feasible arrival by the profile's approach order, then canonical ID.

Scope remains a mock simulator with one target flight and fixed surrounding reservations.
There is no flight certification, live control-system integration, route geometry, arbitrary surface waiting, speed/altitude control or production deployment.
The only built-in real-data airport profile is DFW/DAL; unsupported rows are rejected or skipped with reasons.
The public source CSVs and local run databases are intentionally excluded from version control.
