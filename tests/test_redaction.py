from __future__ import annotations

from wabot_agent.redaction import mask_email, mask_phone, redact, redact_text


def test_mask_email_basic():
    assert mask_email("operator@example.com") == "o***r@example.com"


def test_mask_email_short_local_part():
    # Local parts <=2 chars get fully masked — `a***a` for `ab` leaks both chars.
    assert mask_email("a@x.io") == "***@x.io"
    assert mask_email("ab@x.io") == "***@x.io"


def test_mask_email_invalid_returns_input():
    assert mask_email("not-an-email") == "not-an-email"


def test_mask_email_empty_returns_input():
    assert mask_email("") == ""


def test_mask_email_no_at_returns_input():
    assert mask_email("plainstring") == "plainstring"


def test_mask_email_multi_at_returns_input():
    # Multiple `@` is not a valid email — leave the input alone rather than
    # accidentally masking some prefix.
    assert mask_email("foo@bar@baz.com") == "foo@bar@baz.com"


def test_mask_email_three_char_local():
    # Three-char local masks to first + *** + last.
    assert mask_email("abc@x.io") == "a***c@x.io"


def test_redact_dict_email_key():
    payload = {"email": "operator@example.com", "ok": True}
    out = redact(payload)
    assert out == {"email": "o***r@example.com", "ok": True}


def test_redact_text_finds_email_inline():
    s = "user operator@example.com just logged in"
    out = redact_text(s)
    assert "operator@example.com" not in out
    assert "o***r@example.com" in out


def test_redact_preserves_bearer_and_phone_behavior():
    # Regression guard for existing behavior — issue #10 must not regress redaction.
    assert "Bearer [REDACTED]" in redact_text("Authorization: Bearer abc.def-ghi")
    assert redact("sk-or-ABCDEF") == "sk-or-[REDACTED]"
    assert mask_phone("+15551234567").startswith("15")


def test_redact_secret_key_overrides_email_marker():
    # A field literally named `secret_email` (matches SECRET_KEYS via the
    # `secret` substring) goes to [REDACTED], not mask_email.
    out = redact({"secret_email": "ops@example.com"})
    assert out == {"secret_email": "[REDACTED]"}


def test_redact_nested_email_in_list():
    payload = {"users": [{"email": "a@b.com"}, {"email": "abcd@b.com"}]}
    out = redact(payload)
    assert out == {"users": [{"email": "***@b.com"}, {"email": "a***d@b.com"}]}
