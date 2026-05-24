"""usage_tracking — cost computation and run-metrics persistence (Phase 6).

Functions:
  load_prices()         -> dict[(provider, model), {prompt_per_1m_usd, completion_per_1m_usd}]
  compute_cost_usd(...) -> float
  record_run_metrics(store, run_id, *, ...) -> None
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .memory import MemoryStore

logger = logging.getLogger(__name__)

_PRICES_PATH = Path(__file__).resolve().parent / "registries" / "llm_prices.json"

# Module-level cache so the JSON is only parsed once per process.
_price_cache: dict[tuple[str, str], dict] | None = None


def load_prices() -> dict[tuple[str, str], dict]:
    """Return {(provider, model): entry} from llm_prices.json.

    Wildcard entries use model="*" and act as a provider-level fallback.
    The cache is populated on the first call and reused thereafter.
    """
    global _price_cache
    if _price_cache is not None:
        return _price_cache

    try:
        raw: list[dict] = json.loads(_PRICES_PATH.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        logger.warning("usage_tracking: could not load llm_prices.json: %s", exc)
        _price_cache = {}
        return _price_cache

    result: dict[tuple[str, str], dict] = {}
    for entry in raw:
        provider = (entry.get("provider") or "").lower()
        model = (entry.get("model") or "").lower()
        result[(provider, model)] = {
            "prompt_per_1m_usd": float(entry.get("prompt_per_1m_usd") or 0.0),
            "completion_per_1m_usd": float(entry.get("completion_per_1m_usd") or 0.0),
        }
    _price_cache = result
    return result


def _invalidate_price_cache() -> None:
    """For tests only — reset the module-level price cache."""
    global _price_cache
    _price_cache = None


def compute_cost_usd(
    provider: str | None,
    model: str | None,
    prompt_tokens: int | None,
    completion_tokens: int | None,
) -> float:
    """Compute cost in USD from token counts.

    Returns 0.0 if any input is None or if the model is not in the price table.
    Falls back to the wildcard "*" entry for the provider when the exact model
    is not listed.
    """
    if provider is None or model is None:
        return 0.0
    if prompt_tokens is None or completion_tokens is None:
        return 0.0

    prices = load_prices()
    key = (provider.lower(), model.lower())
    entry = prices.get(key)
    if entry is None:
        # Try wildcard for this provider
        entry = prices.get((provider.lower(), "*"))
    if entry is None:
        return 0.0

    prompt_cost = prompt_tokens / 1_000_000 * entry["prompt_per_1m_usd"]
    completion_cost = completion_tokens / 1_000_000 * entry["completion_per_1m_usd"]
    return prompt_cost + completion_cost


def record_run_metrics(
    store: MemoryStore,
    run_id: str,
    *,
    subagent_slug: str | None,
    model: str | None,
    provider: str | None,
    prompt_tokens: int | None,
    completion_tokens: int | None,
    latency_ms: int | None,
) -> None:
    """UPDATE the runs row with Phase-6 metric columns.

    Idempotent: re-calling with the same run_id overwrites values.
    Never raises — failures are logged as warnings so the WhatsApp reply
    path cannot be broken by metrics errors.
    """
    try:
        cost_usd = compute_cost_usd(provider, model, prompt_tokens, completion_tokens)
        with store.connect() as conn:
            conn.execute(
                """
                UPDATE runs
                   SET subagent_slug = ?,
                       model         = ?,
                       provider      = ?,
                       prompt_tokens = ?,
                       completion_tokens = ?,
                       cost_usd      = ?,
                       latency_ms    = ?
                 WHERE run_id = ?
                """,
                (
                    subagent_slug,
                    model,
                    provider,
                    prompt_tokens,
                    completion_tokens,
                    cost_usd,
                    latency_ms,
                    run_id,
                ),
            )
            conn.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning("usage_tracking: record_run_metrics failed (run=%s): %s", run_id, exc)
