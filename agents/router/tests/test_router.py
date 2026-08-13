from __future__ import annotations

from types import SimpleNamespace

import pytest

from model_router import ModelRouterError, get_client
from model_router import router


class FakeCompletions:
    def __init__(self, response: object) -> None:
        self.response = response
        self.requests: list[dict[str, object]] = []

    def create(self, **request: object) -> object:
        self.requests.append(request)
        return self.response


def fake_sdk_client(response: object) -> tuple[object, FakeCompletions]:
    completions = FakeCompletions(response)
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    return client, completions


@pytest.mark.parametrize(
    ("role", "expected_provider", "expected_model", "expected_base_url", "key_name"),
    [
        ("mapper", "groq", "llama-3.1-8b-instant", "https://api.groq.com/openai/v1", "GROQ_API_KEY"),
        ("identity", "groq", "qwen3-32b", "https://api.groq.com/openai/v1", "GROQ_API_KEY"),
        ("workflow", "groq", "llama-3.3-70b-versatile", "https://api.groq.com/openai/v1", "GROQ_API_KEY"),
        ("verifier_a", "groq", "kimi-k2", "https://api.groq.com/openai/v1", "GROQ_API_KEY"),
        ("verifier_b", "openai", "gpt-5.6-luna", "https://api.openai.com/v1", "OPENAI_API_KEY"),
    ],
)
def test_get_client_resolves_configured_role(
    monkeypatch: pytest.MonkeyPatch,
    role: str,
    expected_provider: str,
    expected_model: str,
    expected_base_url: str,
    key_name: str,
) -> None:
    monkeypatch.setenv(key_name, "test-key")
    observed: dict[str, str] = {}

    def factory(*, api_key: str, base_url: str) -> object:
        observed.update(api_key=api_key, base_url=base_url)
        return object()

    client = get_client(role, client_factory=factory)

    assert (client.provider, client.model) == (expected_provider, expected_model)
    assert observed == {"api_key": "test-key", "base_url": expected_base_url}


def test_get_client_fails_when_provider_key_is_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GROQ_API_KEY", raising=False)

    with pytest.raises(ModelRouterError, match="GROQ_API_KEY") as error:
        get_client("identity")

    assert "test-key" not in str(error.value)


def test_get_client_fails_for_unknown_role() -> None:
    with pytest.raises(ModelRouterError, match="Unknown model-router agent role 'not-a-role'"):
        get_client("not-a-role")


def test_complete_records_metadata_only_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="private model response"))],
        usage=SimpleNamespace(prompt_tokens=12, completion_tokens=7, total_tokens=19),
    )
    sdk_client, completions = fake_sdk_client(response)
    evidence_calls: list[dict[str, object]] = []
    monkeypatch.setattr(router, "record_evidence", lambda **kwargs: evidence_calls.append(kwargs))

    client = get_client("identity", client_factory=lambda **_kwargs: sdk_client)
    result = client.complete([{"role": "user", "content": "private prompt"}])

    assert result == "private model response"
    assert completions.requests == [
        {"model": "qwen3-32b", "messages": [{"role": "user", "content": "private prompt"}]}
    ]
    assert evidence_calls == [
        {
            "run_id": "model-router:identity",
            "sequence_number": 1,
            "action_type": "model_completion",
            "request_response_summary": (
                '{"agent_role": "identity", "completion_tokens": 7, "model": "qwen3-32b", '
                '"prompt_tokens": 12, "provider": "groq", "total_tokens": 19}'
            ),
            "artifact_reference": "model-router://groq/qwen3-32b",
            "policy_decision": "allowed",
        }
    ]
    serialized_evidence = str(evidence_calls)
    assert "private prompt" not in serialized_evidence
    assert "private model response" not in serialized_evidence
    assert "test-key" not in serialized_evidence
