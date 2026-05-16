## Summary

<!-- What changed and why (1–3 bullets). -->

## Test plan

- [ ] `uv run pytest -q -m "not live"` and `cd web && npm run test -- --run`
- [ ] `./scripts/verify-phase1.sh` when wabot APIs changed (`SKIP_LIVE=1` for offline only)
- [ ] wabot rebuilt/restarted if daemon APIs changed
- [ ] `./scripts/check-production-hygiene.sh` if deploy/env behavior changed

## wabot sibling repo

<!-- If this PR needs matching wabot changes, link the wabot PR or note "none". -->
