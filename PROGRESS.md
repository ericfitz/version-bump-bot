# Progress

What has been pushed to `origin`. Machine-local, in-flight state lives in the untracked `HANDOFF.md`.

## 2026-10-03

- `main` cd78c33: `feat: version-bump-bot v1 implementation`, squashed from the 29-commit `feat/v1-implementation` branch. It's the fold base for version 0.1.0.
- Repo secrets `VERSION_BUMP_APP_ID` (5178698) and `VERSION_BUMP_APP_PRIVATE_KEY` are set.
- Bootstrap `Version` run 37167462561 passed with "Nothing to bump." No tags exist yet.
- Eric applied the repo settings: squash-only merges with PR_TITLE subjects, and ruleset 24439428 `default-branch` with App 5178698 as the only bypass actor and `guard / Version Guard` required. `doctor` reports all OK.
- PR #1 `feat!: release version-bump-bot 1.0.0` was squash-merged (1049fe0). It records Eric's decisions 11-13 in the spec.
- The bump run pushed `7bd0c65 chore(version): bump version-bump-bot to 1.0.0` and tag `v1.0.0` together in one push.
- `release-alias.yml` created `v1` at 7bd0c65.
- The follow-up `Version` run was skipped by the actor guard, and a re-plan finds nothing pending.
- **v1.0.0 released.** Adopters pin `ericfitz/version-bump-bot/.github/workflows/bump.yml@v1`.
- PR #3 `feat: sync lockfiles that record the project's own version` was squash-merged (cf2035e). Bump commit 75875d0 rewrote `pyproject.toml`, `uv.lock`, `bump.yml` and `guard.yml` to 1.1.0.
- **v1.1.0 released**, and `v1` moved to 75875d0.
- Lockfile sync: spec `docs/superpowers/specs/2026-10-03-lockfile-sync-design.md` (Eric's decisions 14-16), plan `docs/superpowers/plans/2026-10-03-lockfile-sync.md`.
