"""One safe configuration boundary for model provider and model selection."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping

from scope_controller import record_evidence


_CONFIG_PATH = Path(__file__).resolve().parents[1] / "model_router_config.json"


class ModelRouterError(RuntimeError):
    """Raised when the committed router configuration cannot serve a request."""


def _load_config() -> dict[str, Any]:
    with _CONFIG_PATH.open(encoding="utf-8") as config_file:
        return json.load(config_file)


def _openai_factory(*, api_key: str, base_url: str) -> Any:
    """Create the SDK client only after configuration and credentials are validated."""
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise ModelRouterError(
            "The OpenAI Python SDK is required; install agents/router/requirements.txt"
        ) from exc
    return OpenAI(api_key=api_key, base_url=base_url)


def _response_text(response: Any) -> str:
    try:
        content = response.choices[0].message.content
    except (AttributeError, IndexError, TypeError) as exc:
        raise ModelRouterError("Model provider returned a completion with no message text") from exc
    if not isinstance(content, str):
        raise ModelRouterError("Model provider returned a completion with non-text message content")
    return content


def _token_count(usage: Any, field_name: str) -> int | None:
    value = getattr(usage, field_name, None)
    return value if isinstance(value, int) else None


@dataclass
class ModelClient:
    """Thin completion wrapper bound to a single configured agent role."""

    agent_role: str
    provider: str
    model: str
    _sdk_client: Any
    default_reasoning_effort: str | None = None
    _evidence_sequence: int = field(default=0, init=False, repr=False)

    def complete(
        self,
        messages: list[Mapping[str, Any]],
        reasoning_effort: str | None = None,
        response_format: Mapping[str, Any] | None = None,
    ) -> str:
        """Return one text completion and persist metadata-only evidence for it."""
        request: dict[str, Any] = {"model": self.model, "messages": messages}
        selected_reasoning_effort = reasoning_effort or self.default_reasoning_effort
        if selected_reasoning_effort is not None:
            request["reasoning_effort"] = selected_reasoning_effort
        if response_format is not None:
            request["response_format"] = dict(response_format)

        response = self._sdk_client.chat.completions.create(**request)
        text = _response_text(response)
        usage = getattr(response, "usage", None)
        self._evidence_sequence += 1
        metadata = {
            "agent_role": self.agent_role,
            "provider": self.provider,
            "model": self.model,
            "prompt_tokens": _token_count(usage, "prompt_tokens"),
            "completion_tokens": _token_count(usage, "completion_tokens"),
            "total_tokens": _token_count(usage, "total_tokens"),
        }
        record_evidence(
            run_id=f"model-router:{self.agent_role}",
            sequence_number=self._evidence_sequence,
            action_type="model_completion",
            request_response_summary=json.dumps(metadata, sort_keys=True),
            artifact_reference=f"model-router://{self.provider}/{self.model}",
            policy_decision="allowed",
        )
        return text


def get_client(
    agent_role: str, *, client_factory: Callable[..., Any] = _openai_factory
) -> ModelClient:
    """Resolve one role from committed config and construct its OpenAI-compatible client."""
    config = _load_config()
    role_config = config["roles"].get(agent_role)
    if role_config is None:
        known_roles = ", ".join(sorted(config["roles"]))
        raise ModelRouterError(
            f"Unknown model-router agent role {agent_role!r}. Configured roles: {known_roles}."
        )

    provider = role_config["provider"]
    provider_config = config["providers"].get(provider)
    if provider_config is None:
        raise ModelRouterError(f"Model-router config references unsupported provider {provider!r}.")

    key_environment_name = provider_config["api_key_env"]
    api_key = os.environ.get(key_environment_name)
    if not api_key:
        raise ModelRouterError(
            f"Model-router role {agent_role!r} requires environment variable {key_environment_name}."
        )

    return ModelClient(
        agent_role=agent_role,
        provider=provider,
        model=role_config["model"],
        _sdk_client=client_factory(api_key=api_key, base_url=provider_config["base_url"]),
        default_reasoning_effort=role_config.get("reasoning_effort"),
    )
