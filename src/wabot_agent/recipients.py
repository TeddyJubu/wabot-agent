from __future__ import annotations


def recipient_identity_keys(value: str) -> frozenset[str]:
    """Normalize a phone, JID, or LID into comparable identity keys."""
    raw = value.strip().lower()
    keys: set[str] = {raw}
    local = raw.split("@", 1)[0]
    keys.add(local)
    user_part = local.split(":", 1)[0] if ":" in local else local
    keys.add(user_part)
    digits = "".join(ch for ch in user_part if ch.isdigit())
    if digits:
        keys.add(digits)
        if not digits.startswith("+"):
            keys.add(f"+{digits}")
    return frozenset(keys)


def recipients_match(left: str, right: str) -> bool:
    return bool(recipient_identity_keys(left) & recipient_identity_keys(right))


def is_listed_recipient(value: str, allowed: set[str]) -> bool:
    return any(recipients_match(value, item) for item in allowed)


def is_owner_sender(settings: object, sender: str) -> bool:
    """True when sender matches WABOT_AGENT_OWNER_NUMBERS."""
    owners = getattr(settings, "owner_numbers", None) or set()
    return is_listed_recipient(sender, owners)


def is_owner_inbound(settings: object, inbound: object) -> bool:
    """True when sender or chat JID matches owner_numbers (covers @lid device suffixes)."""
    owners = getattr(settings, "owner_numbers", None) or set()
    sender = str(getattr(inbound, "sender", "") or "").strip()
    chat = str(getattr(inbound, "chat", "") or "").strip()
    if sender and is_listed_recipient(sender, owners):
        return True
    return bool(chat and is_listed_recipient(chat, owners))
