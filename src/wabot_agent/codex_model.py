"""OpenAI Responses model wrapper for ChatGPT / Codex subscription backends."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import replace
from typing import Any

from agents.agent_output import AgentOutputSchemaBase
from agents.exceptions import ModelBehaviorError
from agents.handoffs import Handoff
from agents.items import (
    ModelResponse,
    ResponseOutputMessage,
    ResponseOutputText,
    TResponseInputItem,
    TResponseStreamEvent,
)
from agents.model_settings import ModelSettings
from agents.models.interface import Model, ModelTracing
from agents.models.openai_responses import OpenAIResponsesModel
from agents.tool import Tool
from agents.usage import Usage
from openai.types.responses import Response, ResponseCompletedEvent


class CodexSubscriptionModel(Model):
    """Codex ChatGPT subscription requires streamed Responses API calls."""

    def __init__(self, inner: OpenAIResponsesModel) -> None:
        self._inner = inner

    def _model_settings(self, model_settings: ModelSettings) -> ModelSettings:
        # ChatGPT-backed Codex rejects non-streaming, stored responses.
        if model_settings.store is None:
            return replace(model_settings, store=False)
        return model_settings

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
        previous_response_id: str | None = None,
        conversation_id: str | None = None,
        prompt: Any | None = None,
    ) -> ModelResponse:
        resolved = self._model_settings(model_settings)
        final_response: Response | None = None
        text_parts: list[str] = []
        async for chunk in self._inner.stream_response(
            system_instructions,
            input,
            resolved,
            tools,
            output_schema,
            handoffs,
            tracing,
            previous_response_id=previous_response_id,
            conversation_id=conversation_id,
            prompt=prompt,
        ):
            if getattr(chunk, "type", None) == "response.output_text.delta":
                delta = getattr(chunk, "delta", None)
                if isinstance(delta, str):
                    text_parts.append(delta)
            if isinstance(chunk, ResponseCompletedEvent):
                final_response = chunk.response
        if final_response is None:
            raise ModelBehaviorError(
                "Codex subscription response ended without response.completed"
            )
        output = list(final_response.output)
        if not output and text_parts:
            output = [
                ResponseOutputMessage(
                    id=final_response.id,
                    role="assistant",
                    status="completed",
                    type="message",
                    content=[
                        ResponseOutputText(
                            type="output_text",
                            text="".join(text_parts),
                            annotations=[],
                        )
                    ],
                )
            ]
        usage = (
            Usage(
                requests=1,
                input_tokens=final_response.usage.input_tokens,
                output_tokens=final_response.usage.output_tokens,
                total_tokens=final_response.usage.total_tokens,
                input_tokens_details=final_response.usage.input_tokens_details,
                output_tokens_details=final_response.usage.output_tokens_details,
            )
            if final_response.usage
            else Usage(requests=1)
        )
        return ModelResponse(
            output=output,
            usage=usage,
            response_id=final_response.id,
            request_id=getattr(final_response, "_request_id", None),
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
        previous_response_id: str | None = None,
        conversation_id: str | None = None,
        prompt: Any | None = None,
    ) -> AsyncIterator[TResponseStreamEvent]:
        async for chunk in self._inner.stream_response(
            system_instructions,
            input,
            self._model_settings(model_settings),
            tools,
            output_schema,
            handoffs,
            tracing,
            previous_response_id=previous_response_id,
            conversation_id=conversation_id,
            prompt=prompt,
        ):
            yield chunk
