"""SettingsService — single owner of settings reads, writes, and change notifications.

SR-1 of the simplification roadmap (docs/design/sr-1-settings-service.md).
Today the PATCH handler in api/__init__.py reimplements URL safety, secret
blanking, snapshot validation, and the wabot endpoint/token resync inline
(~137 lines). With SettingsService, the PATCH route shrinks to ~5 lines and
all the logic lives in one place — including the load-bearing rule that a
schema-invalid override on disk cannot be applied to live settings (which
prevents the deploy-time drift bug we hit on 2026-05-23).

Architecture: the service is the only component that mutates Settings or
writes runtime_overrides.json. Other components consume the service:
- API routes call service.patch() / service.read().
- Long-lived collaborators (WabotClient, EventHub) subscribe via
  service.subscribe(callback) at create_app boot time. The hub knows about
  the service; the service never imports the hub. This avoids the
  service<->hub circular import.

Circular-import note:
  settings_service imports from api.schemas (SettingsPatch) and
  api.dependencies (_require_loopback_url). Both are needed only at call
  time inside patch(), not at module import time. We use local imports
  inside patch() for these two to avoid the cycle:
    api.__init__ -> settings_service -> api.schemas -> api.__init__ (cycle)
  The TYPE_CHECKING guard lets type checkers see the SettingsPatch annotation
  without triggering the runtime cycle.

Concurrency: a threading.RLock guards mutation. read() / subscribe() take
the lock to capture a consistent snapshot or subscriber list. patch() takes
the lock for the whole compute-validate-persist-apply-notify path.
Subscribers fire under the lock but should not call back into the service
(they would block; document this contract).
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from fastapi import HTTPException

from .config import Settings
from .providers import get_registry
from .runtime_overrides import (
    MUTABLE_FIELDS,
    SECRET_FIELDS,
    apply_overrides,
    load_overrides,
    save_overrides,
)

if TYPE_CHECKING:
    # Used only for static analysis. At runtime, patch() imports SettingsPatch
    # locally to avoid the circular import cycle described in the module docstring.
    from .api.schemas import SettingsPatch

logger = logging.getLogger(__name__)


SubscriberCallback = Callable[[Settings, frozenset[str]], None]
"""Subscriber receives the new Settings snapshot and the set of changed field names."""


class Unsubscribe:
    """Returned by subscribe(); call to remove the callback.

    Idempotent: calling it more than once is safe (second call is a no-op).
    """

    def __init__(self, fn: Callable[[], None]) -> None:
        self._fn = fn
        self._called = False

    def __call__(self) -> None:
        if not self._called:
            self._called = True
            self._fn()


class SettingsService:
    """Single owner of settings reads, writes, and change notifications.

    Thread safety: a threading.RLock serialises all mutation. read() and
    subscribe() also take the lock so callers always see a consistent view.
    patch() holds the lock for the full validate-persist-apply-notify path.

    Subscriber contract:
    - Callbacks receive (new_settings: Settings, changed_fields: frozenset[str]).
    - They fire synchronously, inside the lock. Do NOT call service.patch()
      from a subscriber — you will deadlock on the RLock.
    - Subscriber exceptions are logged but not propagated; one bad subscriber
      cannot block others or roll back the patch.
    - If the same callable is subscribed twice, both registrations fire;
      calling the returned Unsubscribe removes only the first match.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._lock = threading.RLock()
        self._subscribers: list[SubscriberCallback] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def read(self) -> Settings:
        """Return a deep copy of the current live settings.

        Callers can mutate the returned object without affecting the service.
        """
        with self._lock:
            return self._settings.model_copy(deep=True)

    def patch(self, patch: SettingsPatch) -> Settings:
        """Validate, persist, and apply a settings change.

        Atomic from the caller's perspective: either every field in the patch
        lands AND disk is updated, or nothing changes and an HTTPException is
        raised.

        Validation order (matches the legacy PATCH handler):
        1. Drop fields not in MUTABLE_FIELDS (mass-assignment defence).
        2. Apply 'empty string means None' for SECRET_FIELDS (a blank input
           from the dashboard sets the field to None, removing it from
           overrides on next write).
        3. Validate model_routing format via Pydantic TypeAdapter.
        4. Reject send_policy='allow_all' without confirm_allow_all=true.
        5. URL safety: loopback for wabot_endpoint; per-provider URL rules
           from the registry; base-URL change requires same-PATCH new api key
           to prevent stored-key-to-new-endpoint leak.
        6. Codex base URL validator (ValueError-based); handled separately.
        7. Merge proposed + existing-on-disk overrides; validate the FULL
           merged snapshot via apply_overrides() on a model_copy — catches
           the case where a stale overrides file would become invalid when
           combined with the new patch.
        8. Persist atomically (save_overrides writes .tmp then os.replace).
        9. Apply to live settings.
        10. Notify subscribers.

        Any exception in steps 1-8 leaves live + disk state unchanged.
        """
        with self._lock:
            settings = self._settings

            # Step 1 & 2: build proposed dict; filter to MUTABLE_FIELDS;
            # apply secret-blank-means-None rule.
            proposed: dict[str, Any] = {}
            raw = patch.model_dump(exclude={"confirm_allow_all"}, exclude_none=True)
            for key, value in raw.items():
                if key not in MUTABLE_FIELDS:
                    continue
                if key in {"allowed_recipients", "owner_numbers"}:
                    cleaned = sorted(
                        {str(item).strip() for item in (value or []) if str(item).strip()}
                    )
                    proposed[key] = cleaned
                    continue
                if key in SECRET_FIELDS and isinstance(value, str) and value == "":
                    proposed[key] = None
                    continue
                proposed[key] = value

            # Step 3: validate model_routing if present.
            if "model_routing" in proposed:
                routing_raw = proposed["model_routing"]
                if not isinstance(routing_raw, dict):
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            'model_routing must be a dict (e.g. {"chat": '
                            '{"provider": "openai", "model": ""}})'
                        ),
                    )
                try:
                    from pydantic import TypeAdapter

                    from .model_routing import ModelChoice, ModelPurpose

                    _ta = TypeAdapter(dict[ModelPurpose, ModelChoice])
                    validated_routing = _ta.validate_python(routing_raw)
                except Exception as exc:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Invalid model_routing: {exc}",
                    ) from exc
                # Store as serialisable plain dicts for JSON persistence.
                proposed["model_routing"] = {
                    purpose.value: choice.model_dump()
                    for purpose, choice in validated_routing.items()
                }

            # Step 4: allow_all confirmation gate.
            if proposed.get("send_policy") == "allow_all" and not patch.confirm_allow_all:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "Setting send_policy=allow_all removes the recipient guard. "
                        "Pass confirm_allow_all=true to acknowledge."
                    ),
                )

            # Step 5a: wabot must stay on loopback.
            # Local import avoids the circular:
            #   settings_service -> api.dependencies -> (api package) -> settings_service
            if "wabot_endpoint" in proposed:
                from .api.dependencies import _require_loopback_url  # noqa: PLC0415
                _require_loopback_url("wabot_endpoint", proposed["wabot_endpoint"])

            # Step 5b: provider-registry URL safety + base-URL-change-requires-key rule.
            for _spec in get_registry().values():
                if _spec.base_url_field is None or _spec.url_safety_validator is None:
                    continue
                if _spec.base_url_field not in proposed:
                    continue
                _new_url = proposed[_spec.base_url_field]
                _spec.url_safety_validator(_spec.base_url_field, _new_url)
                if _spec.secret_field is not None:
                    _stored_url = getattr(settings, _spec.base_url_field, None)
                    if _new_url != _stored_url and _spec.secret_field not in proposed:
                        raise HTTPException(
                            status_code=400,
                            detail=(
                                f"Changing {_spec.base_url_field} requires "
                                f"{_spec.secret_field} in the same PATCH so the "
                                "existing stored key is not sent to a new endpoint."
                            ),
                        )

            # Step 6: codex base URL uses a different (ValueError-raising) validator.
            if "codex_base_url" in proposed:
                try:
                    from .codex_auth import require_safe_codex_url

                    require_safe_codex_url(proposed["codex_base_url"])
                except ValueError as exc:
                    raise HTTPException(status_code=400, detail=str(exc)) from exc
                if (
                    proposed["codex_base_url"] != settings.codex_base_url
                    and "codex_access_token" not in proposed
                ):
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            "Changing codex_base_url requires codex_access_token in the "
                            "same PATCH so the existing stored token is not sent to a "
                            "new endpoint."
                        ),
                    )

            # Step 7: merge with existing disk overrides; validate the full merged
            # snapshot on a model_copy — catches stale/manually-edited overrides.
            merged = load_overrides(settings.runtime_overrides_path)
            merged.update(proposed)

            snapshot = settings.model_copy(deep=True)
            try:
                apply_overrides(snapshot, merged)
            except Exception as exc:  # pydantic ValidationError or other
                raise HTTPException(status_code=400, detail=str(exc)) from exc

            # Step 8: persist to disk first. If this raises, live settings stay
            # unchanged (disk is authoritative on next restart).
            save_overrides(settings.runtime_overrides_path, merged)

            # Step 9: apply to live settings.
            changed_fields = apply_overrides(settings, proposed)

            # Step 10: notify subscribers. Exceptions are logged but not propagated.
            changed_frozen = frozenset(changed_fields)
            new_snapshot = settings.model_copy(deep=True)
            for cb in list(self._subscribers):
                try:
                    cb(new_snapshot, changed_frozen)
                except Exception as exc:  # noqa: BLE001
                    logger.exception("SettingsService subscriber raised: %s", exc)

            return new_snapshot

    def subscribe(self, callback: SubscriberCallback) -> Unsubscribe:
        """Register a callback to fire after each successful patch().

        Returns an Unsubscribe handle. Calling it removes the callback.

        Callbacks receive (new_settings: Settings, changed_fields: frozenset[str]).
        They should be small and side-effect-only. Do NOT call service.patch()
        from inside a subscriber — you would deadlock on the RLock.

        If the same callable is subscribed twice, both registrations fire;
        calling the returned Unsubscribe removes only the first match.
        """
        with self._lock:
            self._subscribers.append(callback)

        def _remove() -> None:
            with self._lock:
                try:
                    self._subscribers.remove(callback)
                except ValueError:
                    pass

        return Unsubscribe(_remove)
