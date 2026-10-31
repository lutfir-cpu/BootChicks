"""Typed, bounded contracts shared by ingestion, agents and the simulator."""

import hashlib
import json
from datetime import datetime, timezone
from typing import Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

Role = Literal["ATC", "PILOT", "GROUND"]
ROLES: tuple[Role, ...] = ("ATC", "PILOT", "GROUND")
Mode = Literal["stub", "live", "recorded_replay", "fallback"]


def digest(value) -> str:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    @field_validator("*", mode="after")
    @classmethod
    def canonical_utc(cls, value):
        def convert(item):
            if isinstance(item, datetime):
                return item.astimezone(timezone.utc)
            if isinstance(item, tuple):
                return tuple(convert(v) for v in item)
            if isinstance(item, dict):
                return {key: convert(v) for key, v in item.items()}
            return item

        return convert(value)


class Window(Model):
    start: AwareDatetime
    end: AwareDatetime

    @field_validator("start", "end")
    @classmethod
    def utc(cls, value):
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def ordered(self):
        if self.start >= self.end:
            raise ValueError("Interval end must follow its start.")
        return self


class Reservation(Model):
    resource: str
    interval: Window
    flight_id: str
    wake_class: str = "M"


class RawFlight(Model):
    YEAR: int
    MONTH: int
    DAY: int
    DAY_OF_WEEK: int
    AIRLINE: str
    FLIGHT_NUMBER: str
    TAIL_NUMBER: str | None
    ORIGIN_AIRPORT: str
    DESTINATION_AIRPORT: str
    SCHEDULED_DEPARTURE: int
    DEPARTURE_TIME: int | None
    DEPARTURE_DELAY: float | None
    TAXI_OUT: float | None
    WHEELS_OFF: int | None
    SCHEDULED_TIME: float
    ELAPSED_TIME: float | None
    AIR_TIME: float | None
    DISTANCE: float | None
    WHEELS_ON: int | None
    TAXI_IN: float | None
    SCHEDULED_ARRIVAL: int
    ARRIVAL_TIME: int | None
    ARRIVAL_DELAY: float | None
    DIVERTED: int
    CANCELLED: int
    CANCELLATION_REASON: str | None
    AIR_SYSTEM_DELAY: float | None
    SECURITY_DELAY: float | None
    AIRLINE_DELAY: float | None
    LATE_AIRCRAFT_DELAY: float | None
    WEATHER_DELAY: float | None


class RawAirline(Model):
    IATA_CODE: str
    AIRLINE: str


class RawAirport(Model):
    IATA_CODE: str
    AIRPORT: str
    CITY: str
    STATE: str
    COUNTRY: str
    LATITUDE: float | None
    LONGITUDE: float | None

    @field_validator("LATITUDE", "LONGITUDE", mode="before")
    @classmethod
    def blank_coordinates(cls, value):
        return None if value == "" else value


class Provenance(Model):
    source_type: Literal["historical_csv", "synthetic_fixture"]
    source_url: str | None = None
    file_sha256: dict[str, str] = Field(default_factory=dict)
    csv_line: int | None = Field(default=None, ge=2)
    raw_flight: dict[str, str] = Field(default_factory=dict)
    raw_lookups: dict[str, dict[str, str]] = Field(default_factory=dict)
    filter: str = "WEATHER_DELAY > 15 OR LATE_AIRCRAFT_DELAY > 20; not cancelled/diverted; supported profile"
    skipped_reasons: dict[str, int] = Field(default_factory=dict)


class NormalizedFlight(Model):
    flight_id: str
    airline_code: str
    airline_name: str
    tail_number: str | None
    origin_airport: str
    destination_airport: str
    scheduled_departure: AwareDatetime
    scheduled_gate_arrival: AwareDatetime
    simulated_gate_eta: AwareDatetime
    earliest_touchdown: AwareDatetime
    replay_mapping: str


class Runway(Model):
    id: str
    aircraft_classes: tuple[str, ...]
    approach_ids: tuple[str, ...]
    closed: tuple[Window, ...]
    occupancy_seconds: int = Field(gt=0)
    crosswind_knots: float = Field(ge=0)
    weather_valid: Window


class Edge(Model):
    id: str
    start_node: str
    end_node: str
    duration_seconds: int = Field(gt=0)
    capacity: int = Field(ge=1)
    closed: tuple[Window, ...]


class TaxiPath(Model):
    id: str
    runway_id: str
    gate_id: str
    edge_ids: tuple[str, ...] = Field(min_length=1)


class Approach(Model):
    id: str
    runway_ids: tuple[str, ...]
    duration_seconds: int = Field(gt=0)
    burn_kg: float = Field(ge=0)
    turbulence: float = Field(ge=0)
    valid: Window


class Gate(Model):
    id: str
    aircraft_classes: tuple[str, ...]
    services: tuple[str, ...]
    available: tuple[Window, ...] = Field(min_length=1)
    buffer_seconds: int = Field(ge=0)


class Crew(Model):
    id: str
    skills: tuple[str, ...]
    gate_ids: tuple[str, ...]
    available: tuple[Window, ...] = Field(min_length=1)
    shift_end: AwareDatetime
    max_overtime_seconds: int = Field(ge=0)


class Airport(Model):
    iata_code: str
    timezone: str
    lookup: RawAirport
    slots: tuple[AwareDatetime, ...] = Field(min_length=1, max_length=20)
    runways: tuple[Runway, ...] = Field(min_length=1, max_length=2)
    approaches: tuple[Approach, ...] = Field(min_length=1, max_length=2)
    paths: tuple[TaxiPath, ...] = Field(min_length=1, max_length=3)
    edges: tuple[Edge, ...] = Field(min_length=1)
    gates: tuple[Gate, ...] = Field(min_length=1, max_length=5)
    crews: tuple[Crew, ...] = Field(min_length=1, max_length=3)
    wake_separation_seconds: dict[str, dict[str, int]]
    rolling_arrival_limit: int = Field(ge=1)
    sector_capacity: int = Field(ge=1)
    sector_seconds: int = Field(gt=0)

    @model_validator(mode="after")
    def resources(self):
        if self.lookup.IATA_CODE != self.iata_code:
            raise ValueError("Airport lookup key does not match its profile.")
        for values in (
            self.runways,
            self.approaches,
            self.paths,
            self.edges,
            self.gates,
            self.crews,
        ):
            if len({v.id for v in values}) != len(values):
                raise ValueError("Duplicate resource identifier.")
        if len(set(self.slots)) != len(self.slots):
            raise ValueError("Duplicate landing slot.")
        if any(
            v < 0 for row in self.wake_separation_seconds.values() for v in row.values()
        ):
            raise ValueError("Wake separation values must be nonnegative seconds.")
        # Reject oversized catalogues rather than silently dropping combinations.
        if (
            len(self.slots)
            * len(self.approaches)
            * len(self.paths)
            * len(self.gates)
            * len(self.crews)
            > 1440
        ):
            raise ValueError("Action catalogue exceeds the 1,440-combination bound.")
        return self


class Aircraft(Model):
    tail_number: str | None
    type_label: str
    mapping_source: Literal["mock_fixture", "scenario_override"]
    wake_class: str
    gate_class: str
    crosswind_limit_knots: float = Field(ge=0)
    turbulence_limit: float = Field(ge=0)
    fuel_kg: float = Field(ge=0)
    hold_burn_kg_min: float = Field(gt=0)
    taxi_burn_kg_min: float = Field(ge=0)
    protected_landing_kg: float = Field(ge=0)
    protected_on_block_kg: float = Field(ge=0)
    fuel_policy_components: dict[str, dict[str, float]]
    fuel_policy_notes: str
    required_services: tuple[str, ...]

    @model_validator(mode="after")
    def documented_floors(self):
        for name, floor in (
            ("landing", self.protected_landing_kg),
            ("on_block", self.protected_on_block_kg),
        ):
            components = self.fuel_policy_components.get(name)
            if (
                not components
                or any(v < 0 for v in components.values())
                or abs(sum(components.values()) - floor) > 1e-6
            ):
                raise ValueError(
                    "Protected fuel floors must match their documented, nonnegative components."
                )
        return self


class Connection(Model):
    passengers: int = Field(gt=0)
    boarding_deadline: AwareDatetime
    transfer_seconds_by_gate: dict[str, int]


class ScoringPolicy(Model):
    version: str = "mock-fairness-v1"
    scales: dict[str, float] = Field(
        default_factory=lambda: {
            "delay_min": 60,
            "taxi_min": 20,
            "airborne_fuel_kg": 2000,
            "gate_wait_min": 30,
            "overtime_min": 10,
            "next_departure_delay_min": 30,
        }
    )
    atc_weights: tuple[float, float] = (0.6, 0.4)
    pilot_weights: tuple[float, float] = (0.6, 0.4)
    ground_weights: tuple[float, float, float] = (0.4, 0.3, 0.3)

    @model_validator(mode="after")
    def valid_scales(self):
        required = {
            "delay_min",
            "taxi_min",
            "airborne_fuel_kg",
            "gate_wait_min",
            "overtime_min",
            "next_departure_delay_min",
        }
        if set(self.scales) != required or any(v <= 0 for v in self.scales.values()):
            raise ValueError("All fixed cost scales must be present and positive.")
        for weights in (self.atc_weights, self.pilot_weights, self.ground_weights):
            if any(w < 0 for w in weights) or abs(sum(weights) - 1) > 1e-8:
                raise ValueError("Cost weights must be nonnegative and sum to one.")
        return self


class Snapshot(Model):
    schema_version: Literal["1.0"] = "1.0"
    scenario_id: str
    environment_id: str
    version: int = Field(default=1, ge=1)
    profile_version: str
    clock: AwareDatetime
    valid_until: AwareDatetime
    flight_id: str
    preferred_gate: str
    aircraft: Aircraft
    destination: Airport
    alternates: tuple[Airport, ...] = Field(max_length=1)
    connections: tuple[Connection, ...]
    turnaround_seconds: int = Field(gt=0)
    next_departure_target: AwareDatetime
    reservations: tuple[Reservation, ...]
    policy: ScoringPolicy = Field(default_factory=ScoringPolicy)
    operational_provenance: dict[str, str]

    @property
    def snapshot_version(self):
        return f"{self.environment_id}:v{self.version}"


class Action(Model):
    action: Literal["LAND", "DIVERT"] = "LAND"
    airport: str
    landing_slot: AwareDatetime
    approach_id: str
    taxi_path_id: str
    gate_id: str
    crew_id: str


class CandidatePlan(Model):
    candidate_id: str
    plan_hash: str
    snapshot_version: str
    action: Action
    proposers: tuple[Role, ...] = ()


class CheckResult(Model):
    constraint_id: str
    domain: Role
    passed: bool
    measured: float | str | bool | None
    bound: float | str | bool | None
    unit: str
    margin: float | None
    source_reference: str


class Outcomes(Model):
    touchdown: AwareDatetime
    gate_arrival: AwareDatetime
    service_end: AwareDatetime
    holding_min: float
    airborne_fuel_kg: float
    fuel_touchdown_kg: float
    fuel_gate_kg: float
    landing_margin_kg: float
    gate_margin_kg: float
    taxi_min: float
    gate_wait_min: float
    missed_connections: int
    missed_connection_fraction: float
    overtime_min: float
    next_departure_delay_min: float


class CandidateEvaluation(Model):
    candidate: CandidatePlan
    feasible: bool
    checks: tuple[CheckResult, ...]
    outcomes: Outcomes | None
    domain_costs: dict[str, float]
    reservations: tuple[Reservation, ...]


class Proposal(Model):
    label: Literal["preferred", "compromise", "concession"]
    action: Action
    rationale: str = Field(min_length=1, max_length=1000)
    requested_concessions: tuple[str, ...] = Field(max_length=3)


class ConstraintReference(Model):
    constraint_id: str
    classification: Literal["hard", "soft"]
    priority: int = Field(ge=1, le=10)


class RoundOneResponse(Model):
    sender: Role
    snapshot_version: str
    constraint_references: tuple[ConstraintReference, ...] = Field(max_length=30)
    proposals: tuple[Proposal, ...] = Field(max_length=3)


class Vote(Model):
    candidate_id: str
    plan_hash: str
    decision: Literal["ACCEPT", "REJECT"]
    preference_rank: int = Field(ge=1, le=9)
    reason_codes: tuple[str, ...] = Field(max_length=10)
    rationale: str = Field(min_length=1, max_length=1000)
    proposal_references: tuple[str, ...] = Field(max_length=9)
    accepted_concessions: tuple[str, ...] = Field(max_length=3)


class RoundTwoResponse(Model):
    sender: Role
    snapshot_version: str
    votes: tuple[Vote, ...] = Field(max_length=9)


class AuditEvent(Model):
    event_id: str
    sequence: int
    run_id: str
    timestamp: AwareDatetime
    kind: str
    payload: dict


class ConsensusCertificate(Model):
    plan_hash: str
    snapshot_version: str
    policy_version: str
    accepting_messages: dict[str, str]
    validation_report_hash: str
    commit_event_id: str


class RunResult(Model):
    run_id: str
    schema_version: Literal["1.0"] = "1.0"
    status: Literal["CONSENSUS", "FALLBACK", "ESCALATED", "FAILED"]
    terminal_reason: str
    mode: Mode
    source_provenance: Provenance
    snapshot_version: str
    policy_version: str
    rounds_used: int
    logical_agent_responses: int
    provider_requests: int
    latency_ms: float
    selected_plan: CandidatePlan | None
    evaluation: CandidateEvaluation | None
    consensus_certificate: ConsensusCertificate | None
    fallback_reason: str | None
    baseline: CandidateEvaluation | None
    improvement_metrics: dict[str, float] | None
    audit_event_reference: str

    @model_validator(mode="after")
    def terminal_integrity(self):
        if self.rounds_used > 2:
            raise ValueError("A run cannot exceed two communication rounds.")
        if self.status in ("CONSENSUS", "FALLBACK"):
            if (
                self.selected_plan is None
                or self.evaluation is None
                or not self.evaluation.feasible
                or not all(c.passed for c in self.evaluation.checks)
            ):
                raise ValueError(
                    "A selected action requires a passing authoritative report."
                )
        if self.status == "CONSENSUS":
            certificate = self.consensus_certificate
            if certificate is None or set(certificate.accepting_messages) != set(ROLES):
                raise ValueError("Consensus requires all three recorded acceptances.")
            if len(set(certificate.accepting_messages.values())) != 3:
                raise ValueError(
                    "Consensus requires three distinct acceptance messages."
                )
            if (
                certificate.plan_hash != self.selected_plan.plan_hash
                or certificate.snapshot_version != self.snapshot_version
                or certificate.policy_version != self.policy_version
                or certificate.validation_report_hash != digest(self.evaluation)
            ):
                raise ValueError(
                    "Consensus certificate does not bind this exact report and state."
                )
        elif self.consensus_certificate is not None:
            raise ValueError("Only consensus may carry a consensus certificate.")
        return self


class WorkflowInput(Model):
    schema_version: Literal["1.0"] = "1.0"
    flight_row: RawFlight
    airline_row: RawAirline
    airport_rows: tuple[RawAirport, RawAirport]
    scenario_id: str = "runway_closure_gate_conflict_v1"
    seed: int = 42
    mode: Mode = "stub"
    provenance: Provenance

    @model_validator(mode="after")
    def source_integrity(self):
        if self.provenance.source_type == "historical_csv":
            import re

            from .ingestion import parse_flight

            required = {"flights.csv", "airlines.csv", "airports.csv"}
            if (
                set(self.provenance.file_sha256) != required
                or any(
                    re.fullmatch(r"[0-9a-f]{64}", h) is None
                    for h in self.provenance.file_sha256.values()
                )
                or self.provenance.csv_line is None
            ):
                raise ValueError(
                    "Historical input requires source-file hashes and the exact CSV line."
                )
            if parse_flight(self.provenance.raw_flight) != self.flight_row:
                raise ValueError(
                    "Typed flight row does not match its preserved raw source."
                )
        return self


class RunRequest(Model):
    trigger: WorkflowInput | None = None
    scenario_id: Literal[
        "runway_closure_gate_conflict_v1", "insufficient_fuel", "no_gate", "diversion"
    ] = "runway_closure_gate_conflict_v1"
    mode: Mode = "stub"
    seed: int = 42
    round_timeout_seconds: float = Field(default=12, gt=0, le=120)
    total_timeout_seconds: float = Field(default=30, gt=0, le=300)
