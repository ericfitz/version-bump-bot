# Version-bump bot: design

- Status: Spec approved by Eric (2026-10-03). Implementation plan approved by Eric (2026-10-03): `docs/superpowers/plans/2026-10-03-version-bump-bot.md`.
- Owner: Eric Fitzgerald
- Home: new repo `ericfitz/version-bump-bot` (this document is copied there as its founding spec)
- Related: tmi PR #1024 (held, then superseded), tmi issue #627, ADRs `2026-09-28-adr-versioning-docs-skip-and-schema-decoupling.md` and `2026-10-02-adr-post-merge-version-bump.md`

## Human-made decisions (Eric Fitzgerald, 2026-10-02 to 2026-10-04)

1. Versions are bumped **after merge on the default branch**, not inside each PR. In-PR bumps caused a conflict on every concurrent PR, plus a transient Version Check failure on every PR.
2. Build **two portable bots, independent of any tmi repo**, that can be installed on any of Eric's repos: this **version-bump** bot, and **ericfitz-deps-bot** as a general dependency bot (separate design, later). They must work together gracefully. Coupling between them is not a goal in itself.
3. Each bot lives in its own repo with its own agent. The tmi agent hands off. The agents for tmi and tmi-ux integrate the finished bot.
4. **Hold tmi PR #1024**, and don't give deps-bot main-push rights in the meantime. #1024's fold logic and tests seed this bot, and tmi adopts the bot directly.
5. **Runtime:** a reusable workflow plus a small Python CLI. The App is only an identity. There is no hosted service.
6. **v1 scope:** multiple version streams, release tags, post-bump build hooks, and a PR guard check.
7. **Adopting repos require squash-only merges with PR-title commit subjects.**
8. **Implementation:** a standard-library-only Python CLI run with `uv`, pinned by tag (approach A, over generalized bash or a JavaScript action).
9. **Test repositories are local only.** Tests and fixtures create scratch repos with `git init` in temp directories. They never add a remote, never call `gh repo create`, never push anywhere, and never create or delete repositories on GitHub.
10. **Location (2026-10-03, revised the same day): one repo per bot**, `ericfitz/version-bump-bot` and later `ericfitz/deps-bump-bot`. This replaces an earlier choice of an `ericfitz/github-apps` monorepo: the bots share nothing at runtime, and separate repos give plain root workflows and tags, per-bot settings and alerts, one agent per repo, and deps-bump-bot as version-bump-bot's first outside adopter.
11. **The App holds Workflows read/write (2026-10-03).** A bump commit that rewrites a file under `.github/workflows/` is rejected without it. This repo's own targets are `bump.yml` and `guard.yml`, and adopters can have the same kind of target.
12. **The bump commit and its tags go up in one `git push --atomic` (2026-10-03, confirming an agent ruling).** Either both land or neither does, so `main` never carries a bumped version without its tag. The trade-off: if an adopter adds a tag ruleset without the App as a bypass actor, the whole release fails instead of releasing without a tag. The error names the fix.
13. **deps-bump-bot PRs get no special treatment (2026-10-03).** Their titles are not `feat` or breaking, so each one bumps patch.
## Goals

- Installing the bot on any repo gives exactly one version increment per merged PR, with no PR-time edits to version files, no merge conflicts on version state, and no checks that fail transiently.
- Repo-specific needs (several version streams, generated files, release tags) are declared in config, not coded per repo.
- The bot cannot trigger itself in a loop.

## Non-goals (v1)

- Merge-commit or rebase-merge repos (decision 7).
- A hosted webhook service (decision 5).
- Dependency updates. That's deps-bot's job. Dependency PRs are ordinary PRs and get bumped like any other change.
- Changelogs or GitHub Releases. Tags only.

## Architecture

### Repo layout (`ericfitz/version-bump-bot`)

- `pyproject.toml`, `src/version_bump/`: Python package, standard library only (`tomllib`, `json`, `re`, `subprocess` for git, `argparse`). CLI entry point `version-bump` with subcommands `plan`, `apply`, `guard` and `doctor`.
- `tests/`: pytest, run with `uv run pytest`. Fixtures build scratch git repos in temp dirs (decision 9).
- `.github/workflows/bump.yml` and `.github/workflows/guard.yml`: the reusable workflows (`on: workflow_call`). `.github/workflows/ci.yml`: lint and tests.
- **Releases:** semver tags `vX.Y.Z` plus a moving major tag `v1`. Callers pin `@v1` or an exact tag. The reusable workflow checks out `ericfitz/version-bump-bot` at the same tag to get the CLI. A called workflow can't read its own ref, so the release process writes the release tag into the workflow file as a constant, and CI checks that the constant matches `pyproject.toml`'s version.
- **Visibility:** if the repo is private, its Actions access setting must allow use from Eric's other repositories (Settings → Actions → Access). A public repo needs nothing extra.
- The repo adopts its own bot: a `pyproject.toml` stream (`project.version`) with `tag = "v{version}"`. Every release therefore exercises the full path.

### GitHub App: `ericfitz-version-bump`

- Permissions: Contents read/write, Workflows read/write (decision 11) and Metadata read. No webhook events.
- On each adopting repo it is the **only** bypass actor on the default-branch ruleset, so it can push the bump commit and tags.
- Secrets in each adopting repo: `VERSION_BUMP_APP_ID` and `VERSION_BUMP_APP_PRIVATE_KEY`. Repos that run Dependabot also need them in the Dependabot secret store. The guard needs no secrets.

### Adopting a repo

1. Install the App on the repo and set the two secrets (the operator runs `gh secret set` locally; values never go into chat or logs).
2. Add `.github/version-bump.toml` (see Config).
3. Add a thin caller workflow:

```yaml
name: Version
on:
  push: { branches: [main] }
  pull_request: { branches: [main] }
  workflow_dispatch:
jobs:
  guard:
    if: github.event_name == 'pull_request'
    uses: ericfitz/version-bump-bot/.github/workflows/guard.yml@v1
  bump:
    if: github.event_name != 'pull_request'
    uses: ericfitz/version-bump-bot/.github/workflows/bump.yml@v1
    with:
      setup: go,oapi-codegen@v2.7.1   # toolchains the repo's hooks need; empty when there are no hooks
    secrets: inherit
```

4. Repo settings: allow squash merges only, with squash commit title `PR_TITLE`. Add the App as the ruleset bypass actor and make "Version Guard" a required check. `version-bump doctor` verifies all of this read-only and prints the exact `gh api` commands for anything missing.

## Config: `.github/version-bump.toml`

```toml
[merge]
skip_paths = ["docs/**", "PROGRESS.md", "**/*.md"]   # a commit touching only these bumps nothing

[[stream]]
name = "server"
source = { file = ".version", format = "json-semver" }   # {"major","minor","patch",...} object
targets = [
  { file = "api/version.go", regex = 'VersionMajor = "(?P<major>\d+)"' },
  { file = "api/version.go", regex = 'VersionMinor = "(?P<minor>\d+)"' },
  { file = "api/version.go", regex = 'VersionPatch = "(?P<patch>\d+)"' },
]
breaking = "minor"
tag = "v{version}"

[[stream]]
name = "schema"
source = { file = "api-schema/tmi-openapi.json", format = "json-path", path = "info.version" }
trigger = { changed = ["api-schema/tmi-openapi.json"], ignore_json_paths = ["info.version"] }
breaking = "major"
after = ["make generate-api"]
verify = ["scripts/check-embedded-spec.sh"]
```

### Formats (v1)

- `json-semver`: an object with integer `major`, `minor` and `patch` fields. Other fields are preserved.
- `json-path`: a dotted path to a string `X.Y.Z`, e.g. `info.version` or `version` in `package.json`.
- `toml-path`: a dotted path to a string `X.Y.Z`, e.g. `project.version` in `pyproject.toml`. Writes are line-preserving edits; only the value is replaced.
- `regex`: a pattern with either named groups `major`, `minor` and `patch`, or one named group `version` holding `X.Y.Z`. It must match exactly once in the file.

Writers change only the version value and keep all other bytes. Every stream also accepts an optional `prerelease` value, which is left untouched.

## Bump rules

Folded over every pending commit, oldest first, for each stream:

1. **Pending commits** are the first-parent commits on the default branch after the most recent commit that changed any stream's source value.
2. A commit whose changed paths all match `merge.skip_paths` bumps nothing.
3. A stream with a `trigger` bumps only for commits that change one of its `changed` paths. For JSON files, `ignore_json_paths` are removed before comparing, so the bot's own edits never count as a trigger.
4. **Bump level** comes from the commit subject, which is the PR title (decision 7):
   - `^feat(\(.+\))?!?:` gives minor (patch resets).
   - A breaking marker `^[a-z]+(\(.+\))?!:` gives the stream's `breaking` level (`major` or `minor`).
   - Anything else gives patch.
   - If the subject has both `feat` and `!`, the breaking level applies.
5. The **source file is the single source of truth**. `apply` writes the source, then rewrites every target to match. `guard` fails if targets disagree with the source.

## CLI

- `plan [--ref REF]`: read-only. Prints JSON with `pending` (a list of commit, subject and the streams it bumps), `streams` (name, from, to, tag, after) and `base`. When nothing is pending, `pending` is empty and nothing is to be bumped.
- `apply --plan FILE`: writes the source and target files for each bumped stream. It doesn't run hooks or commit.
- `guard --base SHA [--head SHA]`: read-only. Fails if any stream's source value or regex-captured target value differs between base and head. Regenerated files that only contain the version, such as `api/api.go`, never trip it, because it compares values, not files. Then it runs each stream's `verify` commands at head.
- `doctor`: read-only. Uses `gh api` to check squash-only merging, `PR_TITLE` titles, the bypass actor, the required check and the config's validity. Prints the fix commands for anything wrong.

## Workflows

### `bump.yml` (caller runs it on push to the default branch, or `workflow_dispatch`)

1. **Skip guard:** do nothing if the head commit was authored by the App's bot user and its subject starts with `chore(version)`.
2. Mint an installation token with `actions/create-github-app-token`, and check out the default branch with full history using that token.
3. `plan`. If nothing is pending, exit successfully.
4. Set up the toolchains named in `setup`, then run `apply`.
5. Run each bumped stream's `after` hooks. A hook failure fails the job, and nothing is pushed.
6. Re-run `plan` against the working tree, as if committed, and require nothing pending. This proves the commit is self-consistent.
7. Make one commit, with subject `chore(version): bump <stream> to X.Y.Z[, <stream> to A.B.C]` and a body listing the folded commits.
8. Create tags locally at that commit for streams that declare `tag`. This is idempotent: an existing tag on the same commit is fine, and an existing tag on a different commit is a hard error, raised before anything is pushed. It never moves a tag. Then push the commit and the tags to the default branch in one `git push --atomic`, so either both land or neither does. *(Decision 12. The original text pushed the commit, then the tags, so a failed tag push left a bumped version with no tag and no way to recover.)*
9. **Push rejected:**
   - If the default branch moved, exit successfully; that merge's own run folds everything.
   - Otherwise, fail with a message pointing at the bypass actor.

**Concurrency:** group `version-bump-${{ github.repository }}`, with `cancel-in-progress: false`. Each run folds every pending commit, so a queued run that GitHub drops loses nothing.

**No cascade:** App-token pushes do start workflows, so the bot relies on two independent guards, either of which is enough. The skip guard (step 1), and the fold base (bump rule 1): the bump commit changes the source values, so a rerun computes nothing pending.

### `guard.yml` (pull_request)

Checks out the PR head with full history, computes the merge-base with the default branch, and runs `guard`. The required check's name is "Version Guard". It never depends on another job, so it cannot fail transiently.

## Testing

- pytest with fixtures that build scratch repos via `git init` in `tmp_path`, local only (decision 9). They set `commit.gpgsign=false` and a fixed author, and pass `stdin=DEVNULL` to subprocesses.
- **Fold cases:** fix, feat, a breaking change at each `breaking` level, docs-only commits, triggered vs. untriggered streams, several pending commits, and a bump right after a bump commit (no cascade).
- **Formats:** round-trip read and write for each format, byte preservation, a regex that matches 0 or 2+ times (error), and targets syncing to the source.
- **Guard:** the value changed in the source or a target (fail), only a regenerated file changed (pass), and a `verify` failure.
- **Tags:** create, idempotent re-run, and a conflicting existing tag (error).
- **`doctor`:** fixture JSON for the repo settings and ruleset (no network).
- CI (`ci.yml`): `ruff check`, `ruff format --check`, `uv run pytest`, plus the check that the workflow's embedded release tag matches `pyproject.toml`. The repo adopts the bot for itself.

## Rollout and handoff

1. **tmi agent:**
   - Creates `ericfitz/version-bump-bot` (the one deliberate repo creation, not a test artifact), adds it to `.local/repos.json` via the provision script, and seeds it with this spec, the plan and, as reference, #1024's `plan-pending`/`check-pr-untouched` logic and self-tests.
   - Registers the work on Agentbus as a `tasks/version-bump-bot` list and hands off to the version-bump-bot agent.
   - Eric creates the GitHub App in the UI and sets the secrets.
2. **version-bump-bot agent:** builds the bot through `v1.0.0` under writing-plans and subagent-driven development, adopting the bot on its own repo.
3. **tmi integration (tmi agent):**
   - Closes #1024 and opens a replacement PR. It removes `.github/workflows/version-bump.yml`, removes the version subcommands from `scripts/ci-version-bump.sh` (keeping embedded-spec decoding as `scripts/check-embedded-spec.sh`), and adds the config and caller workflow. It also updates CLAUDE.md and the ADRs.
   - Eric applies the ruleset and repo-setting changes (squash-only, `PR_TITLE`, bypass actor, the "Version Guard" required check in place of "Version Check"). The auto-mode classifier blocks the agent from these.
4. **tmi-ux integration:** the tmi-ux agent follows the same checklist. Its post-merge tag job is replaced by the stream's `tag`.
5. **deps-bump-bot:** a separate brainstorm and spec, built in its own repo `ericfitz/deps-bump-bot` after version-bump-bot v1 ships, adopting version-bump-bot like any other repo. The `ericfitz-deps-bot` App is reused.
