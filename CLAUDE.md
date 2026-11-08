# bonneaffaire

## Agent skills

### Issue tracker

Issues live as local markdown files under `.scratch/<feature-slug>/`. See `docs/agents/issue-tracker.md`.

### Triage labels

Default vocabulary (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`), recorded as a `Status:` line in each issue file. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: one `GLOSSARY.md` and `docs/adr/` at the repo root. See `docs/agents/domain.md`.

## Development

- Python, managed with `uv` (see `docs/adr/0001-python-over-rust.md`).
- Lint and format with `ruff` (`uv run ruff check`, `uv run ruff format`).
- Type-check with `ty` (`uv run ty check`).
- Test with `pytest` (`uv run pytest`). Live canary tests hit real Providers and are excluded from the default run.
- Before committing, all four must pass: ruff check, ruff format --check, ty check, pytest.
