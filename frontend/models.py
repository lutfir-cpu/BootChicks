"""Validated inputs and audit records for a hypothetical arrival replay."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from bootchicks.capacity import AirportCapacity

Role = Literal["ATC", "Pilot", "Ground"]
Decision = Literal["ACCEPT", "REJECT", "COUNTER", "NEED_INFORMATION"]
ROLES: tuple[Role, ...] = ("ATC", "Pilot", "Ground")


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, frozen=True)


class Interval(Model):
    start: int
    end: int

    @model_validator(mode="after")
    def ordered(self):
        if self.end <= self.start:
            raise ValueError("An interval must end after it starts.")
        return self


class Runway(Model):
    id: str = Field(min_length=1)
    closed: tuple[Interval, ...] = ()
    reservations: tuple[Interval, ...] = ()
    occupancy_min: int = Field(default=2, ge=1)
    separation_min: int = Field(default=3, ge=0)


class Gate(Model):
    id: str = Field(min_length=1)
    compatible: bool = True
    occupied: tuple[Interval, ...] = ()
    handling_available: bool = True


class Scenario(Model):
    name: str
    flight_id: str
    state_version: int = Field(default=1, ge=1)
    nominal_arrival_min: int = Field(default=10, ge=0)
    original_gate: str = "G1"
    fuel_remaining_kg: float | None = Field(default=None, ge=0)
    remaining_plan_fuel_kg: float | None = Field(default=None, ge=0)
    fuel_buffer_kg: float | None = Field(default=None, ge=0)
    holding_burn_kg_min: float | None = Field(default=None, gt=0)
    taxi_min: int = Field(default=8, ge=0)
    turnaround_min: int = Field(default=30, ge=1)
    runways: tuple[Runway, ...] = ()
    gates: tuple[Gate, ...] = ()
    provenance: dict[str, str] = Field(default_factory=dict)
    flight_metadata: dict[str, str | int | float | None] = Field(default_factory=dict)
    airport_capacity: AirportCapacity | None = None

    @model_validator(mode="after")
    def unique_resources(self):
        for resources in (self.runways, self.gates):
            ids = [resource.id for resource in resources]
            if len(ids) != len(set(ids)):
                raise ValueError(
                    "Runway and gate identifiers must be unique within each resource type."
                )
        return self


class Candidate(Model):
    id: str
    version: int
    state_version: int
    runway_id: str
    landing_min: int = Field(ge=0)
    gate_id: str
    gate_in_min: int
    gate_out_min: int


class Check(Model):
    rule_id: str
    role: Role
    passed: bool
    detail: str


class ProposedChanges(Model):
    runway_id: str | None = None
    landing_min: int | None = Field(default=None, ge=0)
    gate_id: str | None = None


class AgentResponse(Model):
    role: Role
    candidate_id: str
    candidate_version: int
    state_version: int
    decision: Decision
    failed_rule_ids: list[str]
    explanation: str = Field(min_length=1, max_length=2000)
    proposed_changes: ProposedChanges | None = None


class RoundRecord(Model):
    number: int
    candidate: Candidate
    checks: tuple[Check, ...]
    responses: tuple[AgentResponse, ...]
    errors: tuple[str, ...] = ()


class Result(Model):
    status: Literal[
        "Agreed", "Fallback recommendation", "No feasible plan", "Missing information"
    ]
    reason: str
    scenario: Scenario
    mode: str
    system_prompts: dict[Role, str] = Field(default_factory=dict)
    plan: Candidate | None = None
    rounds: tuple[RoundRecord, ...] = ()
    final_checks: tuple[Check, ...] = ()
    round_count: int = 0
    agent_message_count: int = 0
    api_request_count: int = 0
    missing_fields: tuple[str, ...] = ()
