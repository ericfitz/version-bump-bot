# version-bump-bot

Done gate: `uv run ruff check . && uv run ruff format --check . && uv run pytest`

## Merging

- Every change to `main` goes through a PR. The repo allows only squash merges, and the squash subject is the PR title.
- The PR title sets the version bump (`.github/version-bump.toml`): `feat:` -> minor, `type!:` -> major, anything else -> patch. A PR that touches only `docs/**` or `*.md` files bumps nothing.

## Decisions

- Eric's design decisions 1-13 are in `docs/superpowers/specs/2026-10-03-version-bump-bot-design.md`, and decisions 14-16 are in `docs/superpowers/specs/2026-10-03-lockfile-sync-design.md`.
