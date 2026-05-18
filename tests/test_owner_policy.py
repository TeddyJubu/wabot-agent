from __future__ import annotations

from wabot_agent.config import Settings
from wabot_agent.memory import InboundMessage
from wabot_agent.recipients import recipients_match
from wabot_agent.tools import _is_send_allowed


def test_recipients_match_phone_variants() -> None:
    assert recipients_match("+6580286424", "6580286424@s.whatsapp.net")
    assert recipients_match("6580286424:2@s.whatsapp.net", "+6580286424")


def test_owner_policy_dashboard_may_message_anyone() -> None:
    settings = Settings(
        send_policy="owner",
        owner_numbers={"+6580286424"},
        allowed_recipients=set(),
    )
    allowed, reason = _is_send_allowed(settings, "+15550009999", inbound=None)
    assert allowed is True
    assert reason == "owner"


def test_owner_policy_stranger_reply_only() -> None:
    settings = Settings(
        send_policy="owner",
        owner_numbers={"+6580286424"},
        allowed_recipients=set(),
    )
    inbound = InboundMessage(
        id="m1",
        sender="+15550001111",
        text="hi",
        chat="+15550001111",
    )
    allowed, reason = _is_send_allowed(
        settings, "+15550001111", inbound=inbound
    )
    assert allowed is True
    assert reason == "reply_to_sender"

    blocked, reason = _is_send_allowed(
        settings, "+15550002222", inbound=inbound
    )
    assert blocked is False
    assert reason == "recipient_not_allowed_for_non_owner"


def test_owner_policy_owner_inbound_may_message_anyone() -> None:
    settings = Settings(
        send_policy="owner",
        owner_numbers={"6580286424@s.whatsapp.net"},
        allowed_recipients=set(),
    )
    inbound = InboundMessage(
        id="m2",
        sender="6580286424@s.whatsapp.net",
        text="text +6599998888 hello",
        chat="6580286424@s.whatsapp.net",
    )
    allowed, reason = _is_send_allowed(
        settings, "+6599998888", inbound=inbound
    )
    assert allowed is True
    assert reason == "owner"


def test_owner_policy_allows_group_chat_reply() -> None:
    settings = Settings(
        send_policy="owner",
        owner_numbers={"+6580286424"},
        allowed_recipients=set(),
    )
    inbound = InboundMessage(
        id="g1",
        sender="111@s.whatsapp.net",
        text="hi",
        chat="120363@g.us",
        is_group=True,
    )

    owner_inbound = InboundMessage(
        id="g2",
        sender="6580286424@s.whatsapp.net",
        text="post to group",
        chat="120363@g.us",
        is_group=True,
    )
    allowed_owner, reason_owner = _is_send_allowed(
        settings, "120363@g.us", inbound=owner_inbound
    )
    assert allowed_owner is True
    assert reason_owner == "owner"

    allowed_reply, reason_reply = _is_send_allowed(
        settings, "120363@g.us", inbound=inbound
    )
    assert allowed_reply is True
    assert reason_reply == "reply_to_group_chat"
