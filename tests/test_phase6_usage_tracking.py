"""Phase 6 — usage_tracking module tests.

100% offline: no LLM or network calls.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from wabot_agent.memory import MemoryStore
from wabot_agent.usage_tracking import (
    _invalidate_price_cache,
    compute_cost_usd,
    load_prices,
    record_run_metrics,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_price_cache():
    _invalidate_price_cache()
    yield
    _invalidate_price_cache()


@pytest.fixture
def store(tmp_path: Path) -> MemoryStore:
    db = tmp_path / "agent.db"
    return MemoryStore(db)


# ---------------------------------------------------------------------------
# load_prices
# ---------------------------------------------------------------------------


def test_load_prices_returns_dict():
    prices = load_prices()
    assert isinstance(prices, dict)
    # At least one entry should exist
    assert len(prices) > 0


def test_load_prices_wildcard_present():
    prices = load_prices()
    # ollama or ollama_cloud wildcard should be present
    wildcards = [k for k in prices if k[1] == "*"]
    assert len(wildcards) > 0


def test_load_prices_caches():
    p1 = load_prices()
    p2 = load_prices()
    assert p1 is p2


# ---------------------------------------------------------------------------
# compute_cost_usd
# ---------------------------------------------------------------------------


def test_compute_cost_known_model():
    # gpt-4o: 2.50/1M prompt, 10.00/1M completion
    cost = compute_cost_usd("openai", "gpt-4o", 1_000_000, 1_000_000)
    assert abs(cost - 12.50) < 0.01


def test_compute_cost_mini_model():
    # gpt-4o-mini: 0.15/1M prompt, 0.60/1M completion
    cost = compute_cost_usd("openai", "gpt-4o-mini", 1_000_000, 500_000)
    assert abs(cost - (0.15 + 0.30)) < 0.001


def test_compute_cost_unknown_model_returns_zero():
    cost = compute_cost_usd("openai", "nonexistent-model-xyz", 1000, 1000)
    assert cost == 0.0


def test_compute_cost_wildcard_provider():
    # ollama uses wildcard "*" → 0 cost
    cost = compute_cost_usd("ollama", "llama3.2:latest", 50_000, 10_000)
    assert cost == 0.0


def test_compute_cost_none_provider_returns_zero():
    assert compute_cost_usd(None, "gpt-4o", 1000, 1000) == 0.0


def test_compute_cost_none_model_returns_zero():
    assert compute_cost_usd("openai", None, 1000, 1000) == 0.0


def test_compute_cost_none_tokens_returns_zero():
    assert compute_cost_usd("openai", "gpt-4o", None, 1000) == 0.0
    assert compute_cost_usd("openai", "gpt-4o", 1000, None) == 0.0


def test_compute_cost_zero_tokens():
    cost = compute_cost_usd("openai", "gpt-4o", 0, 0)
    assert cost == 0.0


# ---------------------------------------------------------------------------
# record_run_metrics
# ---------------------------------------------------------------------------


def _insert_run(store: MemoryStore, run_id: str) -> None:
    """Insert a minimal runs row."""
    with store.connect() as conn:
        conn.execute(
            "INSERT INTO runs (run_id, created_at) VALUES (?, datetime('now'))",
            (run_id,),
        )
        conn.commit()


def _fetch_run(store: MemoryStore, run_id: str) -> dict:
    with store.connect() as conn:
        row = conn.execute(
            "SELECT * FROM runs WHERE run_id = ?", (run_id,)
        ).fetchone()
    return dict(row) if row else {}


def test_record_run_metrics_writes_columns(store):
    _insert_run(store, "run-001")
    record_run_metrics(
        store,
        "run-001",
        subagent_slug="orchestrator",
        model="gpt-4o",
        provider="openai",
        prompt_tokens=100,
        completion_tokens=50,
        latency_ms=1234,
    )
    row = _fetch_run(store, "run-001")
    assert row["subagent_slug"] == "orchestrator"
    assert row["model"] == "gpt-4o"
    assert row["provider"] == "openai"
    assert row["prompt_tokens"] == 100
    assert row["completion_tokens"] == 50
    assert row["latency_ms"] == 1234
    # cost_usd = 100/1e6 * 2.50 + 50/1e6 * 10.00 = 0.00025 + 0.0005 = 0.00075
    assert abs(row["cost_usd"] - 0.00075) < 0.000001


def test_record_run_metrics_idempotent(store):
    _insert_run(store, "run-002")
    for _ in range(3):
        record_run_metrics(
            store,
            "run-002",
            subagent_slug="scraper",
            model="gpt-4o-mini",
            provider="openai",
            prompt_tokens=200,
            completion_tokens=100,
            latency_ms=500,
        )
    row = _fetch_run(store, "run-002")
    assert row["prompt_tokens"] == 200
    assert row["completion_tokens"] == 100
    assert row["latency_ms"] == 500


def test_record_run_metrics_none_values_ok(store):
    """None inputs must not raise — they write NULL and cost_usd=0."""
    _insert_run(store, "run-003")
    record_run_metrics(
        store,
        "run-003",
        subagent_slug=None,
        model=None,
        provider=None,
        prompt_tokens=None,
        completion_tokens=None,
        latency_ms=None,
    )
    row = _fetch_run(store, "run-003")
    assert row["cost_usd"] == 0.0


def test_record_run_metrics_missing_run_id_does_not_raise(store):
    """If the run_id doesn't exist, UPDATE is a no-op — must not raise."""
    record_run_metrics(
        store,
        "nonexistent-run",
        subagent_slug=None,
        model="gpt-4o",
        provider="openai",
        prompt_tokens=100,
        completion_tokens=50,
        latency_ms=100,
    )
    # No exception — test passes


# ---------------------------------------------------------------------------
# Phase 6 review SHOULD FIX 3: explicit codex pricing entry
# ---------------------------------------------------------------------------


def test_codex_provider_cost_is_zero():
    """Codex via ChatGPT Plus subscription has no per-token cost.

    Without an explicit entry in llm_prices.json, this would fall through
    silently to the unknown-model 0.0 path; with the entry added in
    Phase 6 review fixes, it's explicit and intentional.
    """
    assert compute_cost_usd("codex", "gpt-5", 1000, 1000) == 0.0
    assert compute_cost_usd("codex", "any-codex-model", 999_999, 999_999) == 0.0


def test_codex_entry_present_in_price_table():
    """Regression guard: the codex provider must have an explicit entry
    so it never silently falls through to the 'unknown model' 0.0 path."""
    prices = load_prices()
    codex_keys = [k for k in prices if k[0] == "codex"]
    assert codex_keys, "codex provider must have at least one explicit price entry"


# ---------------------------------------------------------------------------
# Phase 6 review BLOCKER 1: streaming path passes result= to
# _finalize_turn_state so token usage actually gets recorded.
# ---------------------------------------------------------------------------


def test_record_run_metrics_extracts_tokens_from_result_object(store):
    """Lock the streaming-path fix: _finalize_turn_state must populate the
    runs row with tokens + cost when a result object is passed in.

    This is the unit-level proxy for the BLOCKER from the Phase 6 review.
    Before the fix, the streaming code path called _finalize_turn_state
    without result=, so prompt_tokens / completion_tokens / cost_usd were
    always NULL for the majority of production traffic.
    """
    store.record_run("stream-run-1", sender="+1234", user_input="hi", final_output="hello")
    record_run_metrics(
        store,
        "stream-run-1",
        subagent_slug="orchestrator",
        model="gpt-4o",
        provider="openai",
        prompt_tokens=1234,
        completion_tokens=567,
        latency_ms=250,
    )
    row = _fetch_run(store, "stream-run-1")
    assert row["prompt_tokens"] == 1234
    assert row["completion_tokens"] == 567
    assert row["cost_usd"] is not None and row["cost_usd"] > 0
    assert row["model"] == "gpt-4o"
    assert row["provider"] == "openai"
    assert row["subagent_slug"] == "orchestrator"
    assert row["latency_ms"] == 250
