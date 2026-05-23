from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from agents import ModelSettings, ModelTracing
from agents.agent_output import AgentOutputSchemaBase
from agents.handoffs import Handoff
from agents.items import (
    ResponseOutputMessage,
    ResponseOutputText,
    TResponseInputItem,
    TResponseStreamEvent,
)
from agents.model_settings import ToolChoice
from agents.models.interface import Model, ModelResponse
from agents.tool import Tool
from agents.usage import Usage
from openai import AsyncOpenAI

from .codex_auth import codex_request_headers, load_codex_credentials
from .codex_model import CodexSubscriptionModel
from .config import Settings
from .llm_provider import (
    active_model_for_purpose,
    max_tokens_for_model,
    omit_tool_choice,
    reasoning_for_model,
    resolved_llm_base_url,
)
from .model_routing import ModelPurpose, ResolvedModel
from .redaction import redact_text

try:
    from agents import OpenAIChatCompletionsModel, OpenAIResponsesModel
except ImportError:  # pragma: no cover - dependency import guard
    OpenAIChatCompletionsModel = None  # type: ignore[assignment]
    OpenAIResponsesModel = None  # type: ignore[assignment]


class OfflineModel(Model):
    """A no-network model for local boot, CI, and smoke tests."""

    async def get_response(
        self,
        system_instructions: str | None,
        input: str | list[TResponseInputItem],
        model_settings: ModelSettings,
        tools: list[Tool],
        output_schema: AgentOutputSchemaBase | None,
        handoffs: list[Handoff],
        tracing: ModelTracing,
        *,
        previous_response_id: str | None,
        conversation_id: str | None,
        prompt: Any | None,
    ) -> ModelResponse:
        prompt_text = redact_text(_input_to_text(input))
        tool_names = ", ".join(tool.name for tool in tools)
        text = (
            "Offline mode is active, so no live LLM or WhatsApp sends ran. "
            f"I received: {prompt_text[:500]}. "
            f"Available tools in live mode: {tool_names}."
        )
        return ModelResponse(
            output=[
                ResponseOutputMessage(
                    id="offline-message",
                    role="assistant",
                    status="completed",
                    type="message",
                    content=[
                        ResponseOutputText(
                            type="output_text",
                            text=text,
                            annotations=[],
                        )
                    ],
                )
            ],
            usage=Usage(requests=1),
            response_id="offline-response",
        )

    async def stream_response(
        self,
        system_instructions: str | None,
        input: str | list[TResponseInputItem],
        model_settings: ModelSettings,
        tools: list[Tool],
        output_schema: AgentOutputSchemaBase | None,
        handoffs: list[Handoff],
        tracing: ModelTracing,
        *,
        previous_response_id: str | None,
        conversation_id: str | None,
        prompt: Any | None,
    ) -> AsyncIterator[TResponseStreamEvent]:
        raise NotImplementedError("OfflineModel does not implement streaming.")


def _routed_provider_is_live(resolved: ResolvedModel, settings: Settings) -> bool:
    """Return True when the *resolved* provider has credentials (or needs none).

    This is the per-purpose analogue of ``settings.live_model_enabled``, which
    only checks the global provider.  We must check here so that a purpose routed
    to a live provider is not incorrectly forced offline just because the global
    provider is un-keyed.

    The global ``offline_mode`` toggle always wins — callers must check that
    separately before calling this helper.
    """
    provider = resolved.provider
    if provider == "openai":
        return bool(settings.openai_api_key)
    if provider == "codex":
        from .codex_auth import load_codex_credentials as _load

        return _load(settings) is not None
    if provider == "openrouter":
        return bool(settings.openrouter_api_key)
    if provider == "ollama_cloud":
        return bool(settings.ollama_api_key)
    # Local ollama — no key required.
    return True


def build_model(
    settings: Settings,
    purpose: ModelPurpose = ModelPurpose.CHAT,
) -> Model:
    """Build the Agents SDK Model object for *purpose*.

    When ``settings.model_routing`` has an entry for *purpose*, that provider
    + model is used.  When *purpose* has no routing entry (today's default for
    all purposes), the global ``settings.model_provider`` is used — identical
    to pre-Phase-2 behaviour.

    The codex path is special-cased (device-flow auth, OpenAIResponsesModel)
    regardless of purpose, preserving all existing codex behaviour.

    Liveness check (Finding 1)
    --------------------------
    The offline/liveness decision is now made against the *routed* provider's
    credentials, not the global ``settings.live_model_enabled`` which only
    inspects the global provider.  The global ``offline_mode`` toggle still
    forces offline regardless.
    """
    # Global offline-mode toggle always wins.
    if settings.offline_mode:
        return OfflineModel()

    # Resolve provider + model for this purpose *before* the liveness check so
    # that a purpose routed to a live provider is not forced offline merely
    # because the global provider has no key.
    resolved = active_model_for_purpose(purpose, settings)

    if not _routed_provider_is_live(resolved, settings):
        return OfflineModel()

    # Codex uses device-flow auth and a different SDK model class.
    # We special-case it here regardless of purpose — any purpose routed to
    # "codex" goes through the same codex auth path.
    if resolved.provider == "codex":
        if OpenAIResponsesModel is None:  # pragma: no cover
            raise RuntimeError("openai-agents is missing OpenAIResponsesModel.")
        credentials = load_codex_credentials(settings)
        if credentials is None:
            return OfflineModel()
        client = AsyncOpenAI(
            api_key=credentials.access_token,
            base_url=resolved.base_url or resolved_llm_base_url(settings),
            default_headers=codex_request_headers(credentials),
        )
        inner = OpenAIResponsesModel(
            model=resolved.model_id,
            openai_client=client,
        )
        return CodexSubscriptionModel(inner)

    if OpenAIChatCompletionsModel is None:  # pragma: no cover
        raise RuntimeError("openai-agents is missing OpenAIChatCompletionsModel.")

    # For openrouter, include the referral headers.
    default_headers: dict[str, str] = {}
    if resolved.provider == "openrouter":
        default_headers = {
            "HTTP-Referer": settings.openrouter_site_url,
            "X-OpenRouter-Title": settings.openrouter_app_title,
        }

    client = AsyncOpenAI(
        api_key=resolved.api_key or "",
        base_url=resolved.base_url or resolved_llm_base_url(settings),
        default_headers=default_headers,
    )
    return OpenAIChatCompletionsModel(
        model=resolved.model_id,
        openai_client=client,
        strict_feature_validation=False,
    )


def model_settings(
    settings: Settings,
    purpose: ModelPurpose | None = None,
) -> ModelSettings:
    """Build the ``ModelSettings`` for the given *purpose* (or the global provider).

    Finding 2 fix
    -------------
    When *purpose* is supplied the routed provider for that purpose drives
    ``tool_choice``, ``reasoning``, token limits, and extra_headers — not the
    global ``settings.model_provider``.  Pass ``purpose=ModelPurpose.CHAT`` from
    ``agent.py`` so the chat agent's settings follow the chat route.

    Backward compat: callers that omit *purpose* get the previous behaviour
    (global provider drives everything), which is correct for non-chat paths
    that haven't been migrated yet.
    """
    # Determine the effective provider to drive the settings decisions.
    if purpose is not None:
        resolved = active_model_for_purpose(purpose, settings)
        effective_provider = resolved.provider
    else:
        effective_provider = settings.model_provider

    if effective_provider == "codex":
        # ChatGPT-backed Codex rejects several OpenAI request knobs.
        kwargs: dict[str, Any] = {"store": False, "parallel_tool_calls": False}
        reasoning = reasoning_for_model(settings)
        if reasoning is not None:
            kwargs["reasoning"] = reasoning
        if not omit_tool_choice(settings):
            kwargs["tool_choice"] = _tool_choice_auto()
        return ModelSettings(**kwargs)

    # Build provider-specific extra_headers.
    if effective_provider == "openrouter":
        extra_headers: dict[str, str] = {
            "HTTP-Referer": settings.openrouter_site_url,
            "X-OpenRouter-Title": settings.openrouter_app_title,
        }
    else:
        extra_headers = {}

    # Determine whether to omit tool_choice for this provider.
    # For routed purposes we check the routed model string; for the global path
    # we use the existing omit_tool_choice helper (which reads settings directly).
    if purpose is not None:
        omit_tc = _omit_tool_choice_for_provider(effective_provider, resolved.model_id)
    else:
        omit_tc = omit_tool_choice(settings)

    # max_tokens and reasoning also depend on the model; use the global helpers
    # (they read settings.model_provider which equals effective_provider on the
    # global path; for routed paths we accept the global values as a safe
    # approximation — a follow-up can add per-purpose overrides).
    kwargs = {
        "temperature": settings.agent_temperature,
        "max_tokens": max_tokens_for_model(settings),
        "parallel_tool_calls": False,
        "extra_headers": extra_headers,
    }
    reasoning = reasoning_for_model(settings)
    if reasoning is not None:
        kwargs["reasoning"] = reasoning
    if not omit_tc:
        kwargs["tool_choice"] = _tool_choice_auto()
    return ModelSettings(**kwargs)


def _omit_tool_choice_for_provider(provider: str, model_id: str) -> bool:
    """Whether to suppress tool_choice for the given provider + model.

    Mirrors ``llm_provider.omit_tool_choice`` but accepts explicit provider +
    model strings so it can be called from the routed code path without a
    Settings object.
    """
    if provider != "openrouter":
        return False
    lowered = model_id.lower()
    if "trinity" in lowered or "thinking" in lowered:
        return False
    return "nemotron" in lowered or ":free" in lowered


def _tool_choice_auto() -> ToolChoice:
    return "auto"


def _input_to_text(input_value: str | list[TResponseInputItem]) -> str:
    if isinstance(input_value, str):
        return input_value
    parts: list[str] = []
    for item in input_value:
        if isinstance(item, dict):
            content = item.get("content")
            if isinstance(content, str):
                parts.append(content)
            elif isinstance(content, list):
                for content_item in content:
                    if isinstance(content_item, dict):
                        text = content_item.get("text") or content_item.get("content")
                        if text:
                            parts.append(str(text))
    return "\n".join(parts)
