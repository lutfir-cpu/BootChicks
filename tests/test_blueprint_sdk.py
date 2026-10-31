import json

import httpx2
from anthropic import AsyncAnthropic

from bootchicks.negotiation import role_contexts
from bootchicks.providers import (
    DEFAULT_PROMPTS,
    PROMPT_VERSION,
    ClaudeProvider,
    StubProvider,
)
from bootchicks.scenario import load_snapshot
from bootchicks.schemas import RoundOneResponse


async def test_real_sdk_schema_and_response_parsing_without_network():
    context = role_contexts(load_snapshot("runway_closure_gate_conflict_v1"))["ATC"]
    fixture = await StubProvider().respond("ATC", 1, context, RoundOneResponse)
    requests = []

    async def respond(request):
        requests.append(json.loads(request.content))
        return httpx2.Response(
            200,
            json={
                "id": "msg-test",
                "type": "message",
                "role": "assistant",
                "model": "test-model",
                "content": [{"type": "text", "text": fixture.model_dump_json()}],
                "stop_reason": "end_turn",
                "stop_sequence": None,
                "usage": {"input_tokens": 10, "output_tokens": 10},
            },
        )

    provider = ClaudeProvider(
        {"PILOT": "Custom pilot instructions."},
        client=AsyncAnthropic(
            api_key="test-key-not-sent-to-network",
            max_retries=0,
            http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(respond)),
        ),
    )
    try:
        parsed = await provider.respond("ATC", 1, context, RoundOneResponse)
        assert parsed == fixture
        assert len(requests) == 1
        assert requests[0]["output_config"]["format"]["type"] == "json_schema"
        assert requests[0]["system"] == DEFAULT_PROMPTS["ATC"]
        await provider.respond("PILOT", 1, context, RoundOneResponse)
        assert requests[1]["system"] == "Custom pilot instructions."
        assert provider.prompt_version.startswith(f"{PROMPT_VERSION}+custom-")
    finally:
        await provider.close()
