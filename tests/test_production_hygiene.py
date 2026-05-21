from __future__ import annotations

import runpy
from pathlib import Path


def _script_globals() -> dict[str, object]:
    script = Path(__file__).resolve().parents[1] / "scripts" / "apply-production-hygiene.py"
    return runpy.run_path(str(script), run_name="not_main")


def test_choose_send_policy_prefers_owner_when_owners_exist() -> None:
    choose = _script_globals()["_choose_send_policy"]
    assert choose({}, {"111@s.whatsapp.net"}, {"222@s.whatsapp.net"}) == "owner"


def test_choose_send_policy_uses_allowlist_with_recipients_only() -> None:
    choose = _script_globals()["_choose_send_policy"]
    assert choose({}, set(), {"222@s.whatsapp.net"}) == "allowlist"


def test_choose_send_policy_falls_back_to_dry_run() -> None:
    choose = _script_globals()["_choose_send_policy"]
    assert choose({}, set(), set()) == "dry_run"


def test_choose_send_policy_preserves_explicit_non_allow_all_policy() -> None:
    choose = _script_globals()["_choose_send_policy"]
    assert choose({"WABOT_AGENT_SEND_POLICY": "owner"}, set(), set()) == "owner"
