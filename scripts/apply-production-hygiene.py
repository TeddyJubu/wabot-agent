#!/usr/bin/env python3
"""Apply local/VPS production hygiene defaults (idempotent).

- send_policy: owner when WABOT_AGENT_OWNER_NUMBERS is set, else allowlist (never allow_all)
- allowed_recipients: union of .env + inbound_messages DB
- operator token: generate if missing in .env
- secret file modes: 0o600
- wabot bind check: 127.0.0.1 only
"""

from __future__ import annotations

import os
import re
import secrets
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from wabot_agent.runtime_overrides import load_overrides, save_overrides  # noqa: E402


def _chmod600(path: Path) -> None:
    if path.exists():
        try:
            os.chmod(path, 0o600)
        except PermissionError:
            print(f"warning: could not chmod 600 {path}", file=sys.stderr)


def _read_env(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.exists():
        return out
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        print(f"warning: could not read {path}: {exc}", file=sys.stderr)
        return out
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        out[key.strip()] = value.strip()
    return out


def _write_env_key(path: Path, key: str, value: str) -> None:
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    pattern = re.compile(rf"^{re.escape(key)}=.*$", re.MULTILINE)
    replacement = f"{key}={value}"
    if pattern.search(text):
        text = pattern.sub(replacement, text, count=1)
    else:
        text = text.rstrip() + f"\n{replacement}\n"
    path.write_text(text, encoding="utf-8")
    _chmod600(path)


def _contacts_from_db(db_path: Path) -> set[str]:
    if not db_path.exists():
        return set()
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "select distinct sender, chat from inbound_messages"
        ).fetchall()
    finally:
        conn.close()
    out: set[str] = set()
    for sender, chat in rows:
        if sender:
            out.add(str(sender).strip())
        if chat:
            out.add(str(chat).strip())
    return {x for x in out if x}


def _default_wabot_env() -> Path:
    candidates = [
        ROOT.parent / "wabot" / "wabot.env",  # /opt/wabot-agent -> /opt/wabot
        ROOT.parent.parent / "wabot" / "wabot.env",  # local nested checkout
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def main() -> int:
    env_path = ROOT / ".env"
    overrides_path = ROOT / "data" / "runtime_overrides.json"
    db_path = ROOT / "data" / "wabot-agent.db"
    wabot_env = Path(os.environ.get("WABOT_ENV", str(_default_wabot_env()))).expanduser()

    env = _read_env(env_path)
    recipients: set[str] = set()
    raw = env.get("WABOT_AGENT_ALLOWED_RECIPIENTS") or env.get("VIGNESH_ALLOWED_RECIPIENTS") or ""
    recipients |= {p.strip() for p in raw.replace(",", " ").split() if p.strip()}
    recipients |= _contacts_from_db(db_path)

    owners: set[str] = set()
    owner_raw = env.get("WABOT_AGENT_OWNER_NUMBERS") or env.get("VIGNESH_OWNER_NUMBERS") or ""
    owners |= {p.strip() for p in owner_raw.replace(",", " ").split() if p.strip()}

    send_policy = "owner" if owners else "allowlist"
    if send_policy == "allowlist" and not recipients:
        print(
            "warning: no allowed_recipients yet — sends will be blocked until you add "
            "numbers/JIDs via Settings or WABOT_AGENT_ALLOWED_RECIPIENTS",
            file=sys.stderr,
        )
    if send_policy == "owner" and not owners:
        print("warning: owner policy selected but no owner_numbers configured", file=sys.stderr)

    # Bootstrap .env for VPS (immutable source of truth).
    _write_env_key(env_path, "WABOT_AGENT_SEND_POLICY", send_policy)
    if owners:
        _write_env_key(env_path, "WABOT_AGENT_OWNER_NUMBERS", ",".join(sorted(owners)))
    if recipients:
        _write_env_key(
            env_path,
            "WABOT_AGENT_ALLOWED_RECIPIENTS",
            ",".join(sorted(recipients)),
        )

    op_key = "WABOT_AGENT_OPERATOR_TOKEN"
    if not env.get(op_key):
        token = secrets.token_hex(32)
        _write_env_key(env_path, op_key, token)
        hint = ROOT / "data" / "operator-token.txt"
        hint.parent.mkdir(parents=True, exist_ok=True)
        hint.write_text(
            f"{token}\n\nUse as ?token= on first dashboard visit or X-Operator-Token header.\n",
            encoding="utf-8",
        )
        _chmod600(hint)
        print(f"generated operator token → {hint} (also in .env)")

    # Runtime overrides (what the running agent reads after restart).
    overrides = load_overrides(overrides_path)
    overrides["send_policy"] = send_policy
    overrides["allowed_recipients"] = sorted(recipients)
    if owners:
        overrides["owner_numbers"] = sorted(owners)
    save_overrides(overrides_path, overrides)
    _chmod600(overrides_path)

    if wabot_env.exists():
        _chmod600(wabot_env)
        bind = _read_env(wabot_env).get("WABOT_HTTP_ADDR", "127.0.0.1:7777")
        host = bind.rsplit(":", 1)[0] if ":" in bind else bind
        if host not in ("127.0.0.1", "localhost"):
            print(f"error: wabot must bind loopback only, got {bind!r}", file=sys.stderr)
            return 1
        loopback_defaults = {
            "WABOT_INBOUND_URL": "http://127.0.0.1:8787/whatsapp/inbound",
            "WABOT_RECEIPT_URL": "http://127.0.0.1:8787/whatsapp/receipt",
            "WABOT_PRESENCE_URL": "http://127.0.0.1:8787/whatsapp/presence",
            "WABOT_HISTORY_SYNC_URL": "http://127.0.0.1:8787/whatsapp/history-sync",
            "WABOT_HISTORY_URL": "http://127.0.0.1:8787/whatsapp/history",
            "WABOT_HISTORY_DB": str(wabot_env.parent / "history.db"),
            "WABOT_HISTORY_BATCH_SIZE": "50",
            "WABOT_HISTORY_MAX_MESSAGES": "500",
        }
        wabot_values = _read_env(wabot_env)
        for key, default in loopback_defaults.items():
            if not wabot_values.get(key):
                _write_env_key(wabot_env, key, default)
                print(f"ok: set {key} in wabot.env")
        wabot_values = _read_env(wabot_env)
        for key in loopback_defaults:
            skip_keys = (
                "WABOT_HISTORY_DB",
                "WABOT_HISTORY_BATCH_SIZE",
                "WABOT_HISTORY_MAX_MESSAGES",
            )
            if key in skip_keys:
                continue
            url = wabot_values.get(key, "")
            if url and "127.0.0.1" not in url and "localhost" not in url:
                print(f"warning: {key} should use loopback, got {url}", file=sys.stderr)

    if wabot_env.exists():
        wabot_dir = wabot_env.parent.resolve()
        if (wabot_dir / "wabot").is_file():
            _write_env_key(env_path, "WABOT_AGENT_WABOT_HOME", str(wabot_dir))
            print(f"ok: set WABOT_AGENT_WABOT_HOME={wabot_dir} (New QR on /pair)")

    print(f"ok: send_policy={send_policy}")
    if owners:
        print(f"ok: owner_numbers={len(owners)}")
    print(f"ok: allowed_recipients={len(recipients)}")
    print("ok: secret file permissions 0600")
    print("next: restart wabot-agent to load overrides; set CF Access before exposing tunnel")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
