"""Pydantic request and response schemas for the wabot-agent HTTP API.

Carved out of ``api/__init__.py`` as part of MASTER ME-1. Every model in this
module is consumed only by route handlers — adding a new endpoint that needs a
new payload shape lives here, not in the route file.

Wire format invariants worth preserving (see CLAUDE.md):

* ``InboundPayload.from_`` uses ``alias="from"`` so the wabot daemon's JSON
  webhook keeps the literal ``"from"`` key. Renaming this field breaks the
  webhook contract.
* ``InboundPayload.to_inbound_message()`` is the single conversion point from
  the wire payload to the internal ``InboundMessage`` aggregate; any new
  webhook field must be added in both spots (or just here if it's only on the
  wire and not persisted).
* ``SettingsPatch.confirm_allow_all`` MUST be ``True`` for the PATCH handler
  to accept ``send_policy="allow_all"`` — this guards the fail-closed send
  boundary.
"""

from __future__ import annotations

from typing import Any  # noqa: F401  (kept for downstream type-hint parity)

from pydantic import BaseModel, Field

from ..memory import InboundMessage


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    session_id: str | None = None


class ChatResponse(BaseModel):
    run_id: str
    session_id: str
    output: str
    live_model: bool


class KnowledgeContentBody(BaseModel):
    content: str = ""


class MemoryFactBody(BaseModel):
    key: str = Field(min_length=1)
    value: str = Field(min_length=1)


class InboundPayload(BaseModel):
    id: str
    timestamp: str | None = None
    from_: str = Field(alias="from")
    chat: str | None = None
    is_group: bool = False
    push_name: str | None = None
    text: str = ""
    media_kind: str | None = None
    media_mime: str | None = None
    media_filename: str | None = None
    has_media: bool = False

    def to_inbound_message(self) -> InboundMessage:
        """Convert the wire payload into the internal ``InboundMessage`` shape."""
        return InboundMessage(
            id=self.id,
            sender=self.from_,
            chat=self.chat,
            text=self.text,
            timestamp=self.timestamp,
            push_name=self.push_name,
            is_group=self.is_group,
            media_kind=self.media_kind,
            media_mime=self.media_mime,
            media_filename=self.media_filename,
            has_media=self.has_media,
        )


class ReceiptPayload(BaseModel):
    type: str = "receipt"
    chat: str
    message_ids: list[str] = Field(default_factory=list)
    receipt_type: str
    timestamp: str | None = None
    sender: str | None = None
    message_sender: str | None = None


class PresencePayload(BaseModel):
    type: str = "chat_presence"
    chat: str
    sender: str
    state: str
    media: str | None = None


class GroupCreateRequest(BaseModel):
    name: str = Field(min_length=1)
    participants: list[str] = Field(default_factory=list)


class GroupUpdateRequest(BaseModel):
    name: str | None = None
    topic: str | None = None
    announce: bool | None = None
    locked: bool | None = None


class GroupParticipantsRequest(BaseModel):
    participants: list[str] = Field(min_length=1)
    action: str = "add"


class GroupInviteRequest(BaseModel):
    reset: bool = False


class GroupJoinRequest(BaseModel):
    invite_link: str = Field(min_length=1)


class HistorySyncSummaryPayload(BaseModel):
    type: str = "history_sync"
    sync_type: str
    conversation_count: int = 0
    message_count: int = 0
    chunk_order: int | None = None
    progress: int | None = None


class HistoryBatchPayload(BaseModel):
    type: str = "history_batch"
    sync_type: str
    messages: list[InboundPayload] = Field(default_factory=list)
    message_count: int = 0
    chunk_order: int | None = None
    progress: int | None = None


class SettingsPatch(BaseModel):
    """Partial update to runtime-mutable settings.

    Any field omitted is unchanged. To clear a secret, pass an empty string.
    `confirm_allow_all` must be true to set send_policy='allow_all'.
    """

    model_provider: str | None = None
    openai_api_key: str | None = None
    openai_base_url: str | None = None
    openai_model: str | None = None
    codex_model: str | None = None
    codex_reasoning_effort: str | None = None
    codex_base_url: str | None = None
    codex_access_token: str | None = None
    codex_account_id: str | None = None
    openrouter_api_key: str | None = None
    openrouter_base_url: str | None = None
    openrouter_model: str | None = None
    ollama_model: str | None = None
    ollama_base_url: str | None = None
    ollama_api_key: str | None = None
    ollama_cloud_base_url: str | None = None
    wabot_endpoint: str | None = None
    wabot_token: str | None = None
    composio_user_id: str | None = None
    send_policy: str | None = None
    allowed_recipients: list[str] | None = None
    owner_numbers: list[str] | None = None
    auto_reply_enabled: bool | None = None
    max_agent_turns: int | None = None
    confirm_allow_all: bool = False


class OpenAITestRequest(BaseModel):
    api_key: str | None = None
    base_url: str | None = None
    model: str | None = None


class OpenRouterTestRequest(BaseModel):
    api_key: str | None = None
    base_url: str | None = None
    model: str | None = None


__all__ = [
    "ChatRequest",
    "ChatResponse",
    "GroupCreateRequest",
    "GroupInviteRequest",
    "GroupJoinRequest",
    "GroupParticipantsRequest",
    "GroupUpdateRequest",
    "HistoryBatchPayload",
    "HistorySyncSummaryPayload",
    "InboundPayload",
    "KnowledgeContentBody",
    "MemoryFactBody",
    "OpenAITestRequest",
    "OpenRouterTestRequest",
    "PresencePayload",
    "ReceiptPayload",
    "SettingsPatch",
]
