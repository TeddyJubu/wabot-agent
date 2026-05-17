# Contributing

Thanks for helping improve **wabot-agent**. This project is open source under the [MIT License](LICENSE); by contributing, you agree your contributions are licensed under the same terms.

## Workflow

`main` is protected: use a branch and open a pull request.

```bash
git checkout main && git pull
git checkout -b feat/short-description
# edit, test, commit
git push -u origin HEAD
gh pr create --base main --title "…" --body "…"
```

Required checks before merge:

- **backend** — `uv run ruff check .` and `uv run pytest -q -m "not live"`
- **evals** — `uv run python evals/run_local.py`
- **web** — `cd web && npm run test -- --run && npm run build`

When a change touches both repos, link the matching [wabot](https://github.com/TeddyJubu/wabot) PR in the description.

## Local verification

```bash
uv sync --all-extras
./scripts/build-web.sh
uv run pytest -q -m "not live"
```

With wabot running locally: `./scripts/verify-phase1.sh` (set `SKIP_LIVE=1` for offline-only).

## Secrets

Do not commit `.env`, `data/`, tokens, or `store.db`. See [README.md](README.md#safety-notes).
