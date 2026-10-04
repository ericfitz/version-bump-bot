# version-bump-bot

Post-merge semantic-version bump bot. Install it on a repo and every merged PR
produces exactly one version increment, with no PR-time edits to version files,
no merge conflicts on version state, and no transiently failing checks.
Repo-specific needs (several version streams, generated files, release tags)
are declared in `.github/version-bump.toml`, not coded per repo.

- Runtime: a reusable GitHub Actions workflow plus a standard-library-only
  Python CLI (`version-bump`), run with `uv`. The GitHub App
  `ericfitz-version-bump` is only an identity; there is no hosted service.
- Design: `docs/superpowers/specs/2026-10-03-version-bump-bot-design.md`.
- Releases: tags `vX.Y.Z` plus the moving alias `v1`. Pin `@v1` or an exact tag.
- Supply chain: every third-party action in the reusable workflows is pinned to a commit SHA.

## How it works

On every push to the default branch, `bump.yml`:

1. skips itself when the push actor is the App's bot user and the head commit
   subject starts with `chore(version)` (guard 1 against cascades);
2. mints an installation token, checks out the default branch with full history;
3. runs `version-bump plan`: pending commits are the first-parent commits after
   the last commit that changed any stream's source **value** (guard 2); each
   one bumps every stream it triggers by its subject (the squash-merge PR title:
   `feat:` -> minor, `type!:` -> the stream's `breaking` level, else patch);
   commits touching only `merge.skip_paths` bump nothing;
4. sets up the toolchains named in `setup`, runs `version-bump apply` (source of
   truth first, then every target), then each bumped stream's `after` hooks;
5. re-plans the working tree and requires nothing pending (the commit is
   self-consistent);
6. commits `chore(version): bump <stream> to X.Y.Z[, ...]` with the folded
   commits in the body, creates each bumped stream's `tag` locally at that
   commit (a tag on a different commit is a hard error, so a conflict fails
   before anything is pushed), then pushes the branch and every tag in ONE
   `git push --atomic`. If the push is rejected because the branch moved, it
   exits 0 (the newer push's run folds everything); any other rejection fails,
   naming the App that must be the bypass actor. Adopters with a tag ruleset
   must add the App as a bypass actor there too (`doctor` does not check tag
   rulesets).

On every pull request, `guard.yml` runs `version-bump guard`: it fails when any
stream's source value or target value differs between the merge base and the
PR head, then runs each stream's `verify` commands. Regenerated files that
merely contain the version never trip it, because it compares values, not
files. The check is named **`guard / Version Guard`** (GitHub names a reusable
workflow's check `<caller job> / <called job>`; keep the caller job id `guard`).

## Adopting a repo

Do the steps in this order. The caller workflow goes in last: once it is on the
default branch, every push runs `bump.yml` and every PR runs the guard.

1. **Install the App** `ericfitz-version-bump` on the repo (Contents read/write,
   Metadata read). Set the two secrets locally; values never go into chat or logs:
   `gh secret set VERSION_BUMP_APP_ID` and `gh secret set VERSION_BUMP_APP_PRIVATE_KEY < key.pem`.
   Repos that run Dependabot also need them in the Dependabot secret store
   (`gh secret set --app dependabot ...`). The App and both secrets must exist
   BEFORE the first merge that includes the caller workflow; otherwise
   `create-github-app-token` fails on every push to the default branch.
2. **Add `.github/version-bump.toml`** (see Config) and commit the version files
   (the fold base is the last commit that set a source value; a repo with no such
   commit fails `plan` with a clear error).

   Warning for a repo that already has a version source: the first bump folds
   EVERY commit since the source value last changed, possibly many. Preview it
   against the default branch before merging the adopting PR:

   ```sh
   uv run --project /path/to/version-bump-bot version-bump plan
   ```

   If the fold is unwanted, land a manual baseline bump BEFORE the guard/caller
   workflow is added. Afterwards the guard rejects a hand bump and only the App
   can push to the default branch.
3. **Repo settings:** squash merges only, squash commit title `PR_TITLE`; the App
   is the **only** bypass actor on the default-branch ruleset (and on any tag
   ruleset covering the stream `tag` pattern); `guard / Version Guard` is a
   required check. Verify everything read-only and get the exact `gh api`
   commands for anything missing; it should come back clean:

   ```sh
   uv run --project /path/to/version-bump-bot version-bump doctor --app-id <APP_ID>
   ```

4. **Add a thin caller workflow last**, `.github/workflows/version.yml`:

   ```yaml
   name: Version
   on:
     push: { branches: [main] }
     pull_request: { branches: [main] }
     workflow_dispatch:
   permissions:
     contents: read
   jobs:
     guard:
       if: github.event_name == 'pull_request'
       uses: ericfitz/version-bump-bot/.github/workflows/guard.yml@v1
     bump:
       if: github.event_name != 'pull_request'
       uses: ericfitz/version-bump-bot/.github/workflows/bump.yml@v1
       with:
         setup: go,oapi-codegen@v2.7.1   # toolchains the hooks need; omit when there are no hooks
       secrets: inherit
   ```

Visibility: if this repo is private, Settings -> Actions -> General -> Access must
allow workflows from Eric's other repositories, and the bot checkout inside the
reusable workflows would need a token that can read it. A public repo needs neither.

## Config: `.github/version-bump.toml`

```toml
[merge]
skip_paths = ["docs/**", "PROGRESS.md", "**/*.md"]   # a commit touching only these bumps nothing

[[stream]]
name = "server"
source = { file = ".version", format = "json-semver" }
targets = [
  { file = "api/version.go", regex = 'VersionMajor = "(?P<major>\d+)"' },
  { file = "api/version.go", regex = 'VersionMinor = "(?P<minor>\d+)"' },
  { file = "api/version.go", regex = 'VersionPatch = "(?P<patch>\d+)"' },
]
breaking = "minor"          # level for a `type!:` subject: major (default) or minor
tag = "v{version}"          # also {major} {minor} {patch}

[[stream]]
name = "schema"
source = { file = "api-schema/tmi-openapi.json", format = "json-path", path = "info.version" }
trigger = { changed = ["api-schema/tmi-openapi.json"], ignore_json_paths = ["info.version"] }
breaking = "major"
after = ["make generate-api"]
verify = ["scripts/check-embedded-spec.sh"]
```

- `source` is the single source of truth; `apply` writes it, then rewrites every
  target to match; `guard` fails if a target disagrees with the source.
- Formats: `json-semver` (object with integer `major`/`minor`/`patch`; other
  fields preserved), `json-path` and `toml-path` (dotted path to a string
  `X.Y.Z`, any suffix such as `-rc1` preserved; TOML writes are line-preserving
  and need the plain `key = "..."` form under a `[table]` header), `regex`
  (named groups `major`/`minor`/`patch`, any subset for a target, or one group
  `version`; must match exactly once). Writers change only the digits.
- A stream without `trigger` bumps on every pending commit. With one, only
  commits changing a `changed` path count; for JSON files the `ignore_json_paths`
  are removed before comparing, so the bot's own edits never count.
- `after` hooks run after `apply`, in the bumped stream's order, from the repo
  root with `sh -c`; a failure fails the job and nothing is pushed. Hooks must
  only modify tracked files (the commit uses `git add -u`).
- `verify` commands run in `guard` at the PR head after the value checks.
- Unknown keys are errors.

## CLI

All subcommands take `--repo DIR` (default cwd) and `--config PATH`
(default `.github/version-bump.toml`). Exit 0 on success, 1 with a one-line
`error: ...` for any expected failure.

| Command | Purpose |
|---|---|
| `plan [--ref REF] [--worktree]` | read-only; prints the plan JSON (`ref`, `pending`, `streams`, `base`, `commit_subject`, `commit_body`). `--worktree` treats uncommitted changes as the bump commit and fails if a target disagrees with its source. |
| `apply --plan FILE` | writes the source and targets of each bumped stream; no hooks, no commit. |
| `hooks --plan FILE` | runs each bumped stream's `after` commands. |
| `guard --base SHA [--head REF]` | read-only value comparison, then `verify` commands. |
| `tag --plan FILE [--commit SHA]` | creates the plan's tags locally (idempotent, never moves one); prints `{"created","existing","all"}`. |
| `doctor [--repo-slug O/R] [--app-id N] [--check-name NAME]` | read-only `gh api` checks of merge settings, bypass actor, required check and config; prints fix commands. |

Reusable workflow inputs (all optional):

| Input | Workflow | Default | Meaning |
|---|---|---|---|
| `setup` | `bump.yml` | `""` | toolchains the `after` hooks need (grammar below) |
| `app_slug` | `bump.yml` | `ericfitz-version-bump` | slug of the App whose bot user pushes the bump; must equal the installed App's slug, or the no-cascade skip guard fails open (one wasted run per bump) |
| `bot_ref` | both | `""` (embedded release tag) | ref of `ericfitz/version-bump-bot` to run |
| `config` | both | `.github/version-bump.toml` | path of the config in the calling repo |

`setup` input grammar for `bump.yml`: comma-separated `go`, `node` (needs
`engines.node` in package.json), `pnpm` (needs `packageManager`), `uv`
(always available), and `name@version` Go installs (`oapi-codegen@v2.7.1` is a
known alias; otherwise give the full module path).

## Development

```sh
uv run pytest                 # local-only scratch repos; never touches GitHub
uv run ruff check . && uv run ruff format --check .
actionlint                    # workflows (CI requires it: ACTIONLINT_REQUIRED=1)
```

## Releasing

This repo adopts its own bot (`.github/version-bump.toml`, caller
`.github/workflows/version.yml` using `uses: ./...` with `bot_ref` = the
current commit). Merging a PR to `main` bumps `pyproject.toml`, rewrites the
`VERSION_BUMP_BOT_REF` constant in `bump.yml` and `guard.yml`, commits, and
pushes the tag `vX.Y.Z`; `release-alias.yml` then force-moves `v1` (the only
tag that ever moves). CI fails if the constant and `pyproject.toml` disagree.
PR titles drive the level: `feat:` minor, `feat!:`/`fix!:` major, else patch.
Merge policy here is the same as for adopters: squash-only, squash commit title =
PR title.

Before the first merge that includes `version.yml`, the App must be installed
on this repo and both secrets set (see Adopting a repo, step 1).

Pending owner decision: the self-adoption release push rewrites
`.github/workflows/bump.yml` and `guard.yml`, so on THIS repo the App also needs
the Workflows: read/write permission; without it GitHub rejects the push
("refusing to allow a GitHub App to create or update workflow"), and the bump
job then reports a misleading bypass-actor error below git's message. This is
specific to this repo and is not part of the adopter permission list.

The first release is a PR titled `feat!: release version-bump-bot 1.0.0`.
