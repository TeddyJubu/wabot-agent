/**
 * Public pairing payload — wire shape mirrors the Python
 * `PairingPayload` (see ../../../tests/snapshots/pairing_payload.schema.json).
 *
 * Per-field policy (operator decision for issue #9):
 *   - Every Pydantic `T | None` field is `T | null` in TypeScript. No
 *     optional-shortcut `field?: T` — the wire always sends the key
 *     (Pydantic emits `null` for unset optionals), so the TS type pins it.
 *   - Non-None defaults (`supported: bool`, `reachable: bool`,
 *     `qr_available: bool`) stay as plain booleans.
 *
 * Drift guard: a snapshot test in __tests__/pairing-schema.test.ts asserts
 * the keys here match `tests/snapshots/pairing_payload.schema.json`. If the
 * Python model changes, regenerate the snapshot with:
 *   uv run python scripts/dump_schemas.py > tests/snapshots/pairing_payload.schema.json
 * and update both this interface and the EXPECTED_KEYS list in the test.
 */
export interface PairingState {
  supported: boolean;
  reachable: boolean;
  logged_in: boolean | null;
  connected: boolean | null;
  qr_available: boolean;
  event: string | null;
  updated_at: string | null;
  expires_at: string | null;
  detail: string | null;
}
