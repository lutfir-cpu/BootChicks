"""Independent Claude role calls and an explicitly labelled offline simulator."""

import json
import os

from engine import feasible_candidates
from models import AgentResponse, ProposedChanges
from prompts import resolve_prompts


class SimulatedAgents:
    mode = "Offline simulation (no Claude calls)"
    is_live = False
    system_prompts = {}

    def evaluate(self, role, scenario, candidate, checks, history):
        failures = [c for c in checks if c.role == role and not c.passed]
        alternatives = (
            feasible_candidates(scenario, candidate.version + 1) if failures else []
        )
        alternate = alternatives[0] if alternatives else None
        return AgentResponse(
            role=role,
            candidate_id=candidate.id,
            candidate_version=candidate.version,
            state_version=candidate.state_version,
            decision="COUNTER" if alternate else "REJECT" if failures else "ACCEPT",
            failed_rule_ids=[c.rule_id for c in failures],
            explanation=" ".join(c.detail for c in failures)
            if failures
            else "All mandatory checks owned by this role pass.",
            proposed_changes=ProposedChanges(
                runway_id=alternate.runway_id,
                landing_min=alternate.landing_min,
                gate_id=alternate.gate_id,
            )
            if alternate
            else None,
        )


class ClaudeAgents:
    mode = "Claude agents"
    is_live = True

    def __init__(self, system_prompts=None):
        from anthropic import Anthropic

        self.system_prompts = resolve_prompts(system_prompts)
        self.client = Anthropic(timeout=25.0, max_retries=0)
        self.model = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5-5")

    def evaluate(self, role, scenario, candidate, checks, history):
        payload = {
            "role": role,
            "scenario": scenario.model_dump(mode="json"),
            "candidate": candidate.model_dump(mode="json"),
            "role_checks": [c.model_dump() for c in checks if c.role == role],
            "history": [r.model_dump(mode="json") for r in history],
        }
        response = self.client.messages.parse(
            model=self.model,
            max_tokens=1200,
            system=self.system_prompts[role],
            messages=[{"role": "user", "content": json.dumps(payload)}],
            output_format=AgentResponse,
        )
        if response.parsed_output is None:
            raise ValueError("No parsed role response.")
        return response.parsed_output
