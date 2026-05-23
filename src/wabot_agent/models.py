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
    llm_default_headers,
    max_tokens_for_model,
    omit_tool_choice,
    reasoning_for_model,
    resolved_llm_base_url,
)
from .model_routing import ModelPurpose
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
    """
    if not settings.live_model_enabled:
        return OfflineModel()

    # Resolve provider + model for this purpose.
    resolved = active_model_for_purpose(purpose, settings)

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


def model_settings(settings: Settings) -> ModelSettings:
    if settings.model_provider == "codex":
        # ChatGPT-backed Codex rejects several OpenAI request knobs.
        kwargs: dict[str, Any] = {"store": False, "parallel_tool_calls": False}
        reasoning = reasoning_for_model(settings)
        if reasoning is not None:
            kwargs["reasoning"] = reasoning
        if not omit_tool_choice(settings):
            kwargs["tool_choice"] = _tool_choice_auto()
        return ModelSettings(**kwargs)

    kwargs = {
        "temperature": settings.agent_temperature,
        "max_tokens": max_tokens_for_model(settings),
        "parallel_tool_calls": False,
        "extra_headers": llm_default_headers(settings),
    }
    reasoning = reasoning_for_model(settings)
    if reasoning is not None:
        kwargs["reasoning"] = reasoning
    if not omit_tool_choice(settings):
        kwargs["tool_choice"] = _tool_choice_auto()
    return ModelSettings(**kwargs)


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
