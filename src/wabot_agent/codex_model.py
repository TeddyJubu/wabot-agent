"""OpenAI Responses model wrapper for ChatGPT / Codex subscription backends."""

from __future__ import annotations

import logging
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

from .context_management import sanitize_codex_session_history

logger = logging.getLogger(__name__)
_CODEX_EMPTY_RETRIES = 4


def _is_nonreplayable_output_item(item: Any) -> bool:
    """Reasoning items break the next Codex request when store=false."""
    typ = getattr(item, "type", None)
    if typ == "reasoning":
        return True
    item_id = getattr(item, "id", None)
    return isinstance(item_id, str) and item_id.startswith("rs_")


def _filter_codex_response_output(output: list[Any]) -> list[Any]:
    return [item for item in output if not _is_nonreplayable_output_item(item)]


def _filter_completed_response(response: Response) -> Response:
    filtered = _filter_codex_response_output(list(response.output))
    if len(filtered) == len(response.output):
        return response
    return response.model_copy(update={"output": filtered})


def _message_from_text_parts(response: Response, text_parts: list[str]) -> list[Any]:
    if not text_parts:
        return []
    return [
        ResponseOutputMessage(
            id=response.id,
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


def _resolve_codex_output(
    response: Response, text_parts: list[str]
) -> list[Any]:
    """Prefer replay-safe output items; fall back to streamed text deltas."""
    output = _filter_codex_response_output(list(response.output))
    if output:
        return output
    return _message_from_text_parts(response, text_parts)


def _sanitize_codex_input(
    input_value: str | list[TResponseInputItem],
) -> str | list[TResponseInputItem]:
    if isinstance(input_value, str):
        return input_value
    if not input_value:
        return input_value
    if all(isinstance(item, dict) for item in input_value):
        return sanitize_codex_session_history(input_value)  # type: ignore[return-value]
    return input_value


class CodexSubscriptionModel(Model):
    """Codex ChatGPT subscription requires streamed Responses API calls."""

    def __init__(self, inner: OpenAIResponsesModel) -> None:
        self._inner = inner

    def _model_settings(self, model_settings: ModelSettings) -> ModelSettings:
        # ChatGPT-backed Codex rejects non-streaming, stored responses.
        # Reasoning items (rs_*) cannot be replayed when store=false — omit them.
        resolved = (
            replace(model_settings, store=False)
            if model_settings.store is None
            else model_settings
        )
        if resolved.store is False and resolved.reasoning is not None:
            return replace(resolved, reasoning=None)
        return resolved

    async def _consume_response_stream(
        self,
        system_instructions: str | None,
        safe_input: str | list[TResponseInputItem],
        resolved: ModelSettings,
        tools: list[Tool],
        output_schema: AgentOutputSchemaBase | None,
        handoffs: list[Handoff],
        tracing: ModelTracing,
        *,
        previous_response_id: str | None,
        conversation_id: str | None,
        prompt: Any | None,
    ) -> tuple[Response, list[str]]:
        final_response: Response | None = None
        text_parts: list[str] = []
        async for chunk in self._inner.stream_response(
            system_instructions,
            safe_input,
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
        return final_response, text_parts

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
        safe_input = _sanitize_codex_input(input)
        output: list[Any] = []
        final_response: Response | None = None
        for attempt in range(_CODEX_EMPTY_RETRIES):
            final_response, text_parts = await self._consume_response_stream(
                system_instructions,
                safe_input,
                resolved,
                tools,
                output_schema,
                handoffs,
                tracing,
                previous_response_id=previous_response_id,
                conversation_id=conversation_id,
                prompt=prompt,
            )
            output = _resolve_codex_output(final_response, text_parts)
            if output:
                break
            logger.warning(
                "Codex returned empty output after filtering (attempt %s/%s)",
                attempt + 1,
                _CODEX_EMPTY_RETRIES,
            )
        if final_response is None:
            raise ModelBehaviorError("Codex subscription response missing")
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
        """Dashboard streaming uses this path — must filter reasoning like get_response."""
        resolved = self._model_settings(model_settings)
        safe_input = _sanitize_codex_input(input)
        text_parts: list[str] = []
        async for chunk in self._inner.stream_response(
            system_instructions,
            safe_input,
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
                filtered = _filter_completed_response(chunk.response)
                output = _resolve_codex_output(filtered, text_parts)
                if output != list(filtered.output):
                    filtered = filtered.model_copy(update={"output": output})
                if filtered is not chunk.response:
                    yield ResponseCompletedEvent(
                        type=chunk.type,
                        response=filtered,
                        sequence_number=chunk.sequence_number,
                    )
                    continue
            yield chunk
