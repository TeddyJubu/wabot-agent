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

from .redaction import redact_text

try:
    from agents import OpenAIChatCompletionsModel
except ImportError:  # pragma: no cover - dependency import guard
    OpenAIChatCompletionsModel = None  # type: ignore[assignment]

from .config import Settings


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
            "Offline mode is active, so I did not call OpenRouter or send WhatsApp messages. "
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


def build_model(settings: Settings) -> Model:
    if not settings.live_model_enabled:
        return OfflineModel()

    if OpenAIChatCompletionsModel is None:  # pragma: no cover
        raise RuntimeError("openai-agents is missing OpenAIChatCompletionsModel.")

    client = AsyncOpenAI(
        api_key=settings.openrouter_api_key,
        base_url=settings.openrouter_base_url,
        default_headers={
            "HTTP-Referer": settings.openrouter_site_url,
            "X-Title": settings.openrouter_app_title,
        },
    )
    return OpenAIChatCompletionsModel(
        model=settings.openrouter_model,
        openai_client=client,
        strict_feature_validation=False,
    )


def _omit_tool_choice(model: str) -> bool:
    """OpenRouter free Nemotron endpoints reject explicit tool_choice values."""
    lowered = model.lower()
    return "nemotron" in lowered or ":free" in lowered


def model_settings(settings: Settings) -> ModelSettings:
    kwargs: dict[str, Any] = {
        "temperature": 0.2,
        "max_tokens": 1800,
        "parallel_tool_calls": False,
        "extra_headers": {
            "HTTP-Referer": settings.openrouter_site_url,
            "X-Title": settings.openrouter_app_title,
        },
    }
    if not _omit_tool_choice(settings.openrouter_model):
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
