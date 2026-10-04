# version-bump-bot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `version-bump-bot`, a portable post-merge semantic-version bump bot (Python CLI + two reusable GitHub Actions workflows) in its own new repo `ericfitz/version-bump-bot`, through its first self-adopted release `v1.0.0`.

**Architecture:** A standard-library-only Python package `version_bump` (under `src/`) exposes a `version-bump` CLI with `plan`, `apply`, `hooks`, `guard`, `tag` and `doctor` subcommands; every decision (fold base, bump level, trigger, format read/write) is a pure function over git output and file text, so it is unit-tested against scratch `git init` repos. Two reusable workflows (`.github/workflows/bump.yml` for the post-merge bump, `.github/workflows/guard.yml` for the PR check) check out the bot at a pinned release tag and drive the CLI; the GitHub App `ericfitz-version-bump` is only an identity (token mint + ruleset bypass). The repo adopts the bot for its own `pyproject.toml`, so every release exercises the full path.

**Tech Stack:** Python >= 3.11 (`tomllib`, `json`, `re`, `subprocess`, `argparse`, `pathlib`, `dataclasses`), `uv` (project runner, `uv_build` backend), pytest + ruff (dev only), GitHub Actions (`actions/create-github-app-token`, `actions/checkout`, `astral-sh/setup-uv`), `actionlint` for workflow validation, `gh` CLI (only `doctor`, read-only).

**Spec:** `docs/superpowers/specs/2026-10-03-version-bump-bot-design.md` in the version-bump-bot repo (copied from tmi at e9377675; owned by the version-bump-bot agent since the 2026-10-03 handoff). Read it before starting any task. The executor works in `ericfitz/version-bump-bot`; every path below is relative to that repo's root. The executor needs no knowledge of tmi; tmi is just one future adopter.

## Global Constraints

Every task's requirements implicitly include this section.

- **Scratch repos are local only.** Tests and fixtures create repos with `git init` inside pytest `tmp_path`. They never add a remote, never run `gh repo create`, never push anywhere, and never create or delete repositories on GitHub (spec decision 9). No test may call `gh`, `git push`, `git fetch`, `git remote`, or `git clone` of a URL.
- **Fixture hygiene.** The scratch-repo fixture sets `commit.gpgsign=false`, `user.name`/`user.email` to fixed values, `GIT_AUTHOR_DATE`/`GIT_COMMITTER_DATE` to a fixed timestamp, `GIT_CONFIG_GLOBAL=/dev/null` and `GIT_CONFIG_NOSYSTEM=1`, uses `git init -b main`, and every subprocess (git or hook) runs with `stdin=subprocess.DEVNULL`. A prior bash test hung reading stdin; do not drop the DEVNULL.
- **Runtime is the Python standard library only** (`tomllib`, `json`, `re`, `subprocess`, `argparse`, `fnmatch`/`pathlib`, `dataclasses`). `pytest` and `ruff` are the only dev dependencies. `requires-python = ">=3.11"` (for `tomllib`). Run everything via `uv` from the repo root: `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`.
- **Reusable workflows** are `.github/workflows/bump.yml` (post-merge bump) and `.github/workflows/guard.yml` (PR check); callers reference `ericfitz/version-bump-bot/.github/workflows/bump.yml@v1` and `.../guard.yml@v1`. `.github/workflows/ci.yml` is the CI workflow (no path filters: the whole repo is the bot). `.github/workflows/release-alias.yml` moves the major alias on tag push. `.github/workflows/version.yml` is this repo's own thin caller (self-adoption).
- **Tags:** immutable `vX.Y.Z` plus a moving `v1` major alias. The reusable bump workflow embeds its own release tag as the constant `VERSION_BUMP_BOT_REF: vX.Y.Z` (a called workflow cannot read its own ref); CI checks it equals `v{project.version}` from `pyproject.toml`, and the self-adoption stream keeps it in sync as a regex target.
- **Visibility:** if `ericfitz/version-bump-bot` is private, its Actions access setting (Settings -> Actions -> General -> Access) must allow workflows from Eric's other repositories, and the bot checkout in both reusable workflows needs a token that can read it. This plan assumes the repo is public (the guard workflow then needs no secrets, as the spec requires).
- **No cascade: two independent guards.** (1) The bump job is skipped when the push actor is the App's bot user (`<app_slug>[bot]`) AND the head commit subject starts with `chore(version)`. (2) The fold base is the last first-parent commit that changed any stream's source **value** (not merely touched the file), so a re-plan after the bump commit is empty.
- **Push rejection:** exit 0 only if the default branch moved during the run (that merge's own run folds everything); otherwise fail loudly, naming the App that must be the ruleset bypass actor.
- **Never log or echo the App private key.** Secrets reach the workflow only via `secrets:` and `actions/create-github-app-token`; the token is used through `actions/checkout`'s `token:` input and the `GH_TOKEN` env of `gh` calls, never printed.
- **Attacker-influenceable strings** (commit subjects, PR titles, file paths) never reach a shell command line by interpolation. The CLI builds the commit subject and body and the workflow passes them to git via files (`git commit -F`), never `-m "$VAR"` with expression interpolation.
- **Formatting:** the code in this plan is not pre-formatted. In every task run `uv run ruff format .` before `uv run ruff format --check .`, and keep all imports at the top of each module in isort order (ruff `I001`); when a later task says "add these imports" to an existing file, merge them into the existing import block (e.g. one `from version_bump.plan import Plan, compute_plan`), never mid-file.
- **Conventional commits** for every commit the executor makes: `<type>(<scope>): <description>` in the imperative mood (`feat(plan): ...`, `test(formats): ...`, `ci: ...`). Squash-merge with PR-title subjects is the merge policy of this repo too.
- **Tags never move.** The bot's `tag` for a stream is created once; an existing tag on the same commit is a no-op, an existing tag on a different commit is a hard error. The moving major alias is created by a separate tag-triggered workflow, never by the bot's `tag` subcommand.
- **Byte preservation.** Format writers change only the version digits and keep every other byte (whitespace, key order, line endings, trailing newline, prerelease suffixes).

## Review Focus

Input classes the spec implies but which are easy to get wrong; each one is pinned by a named test in the task that owns the code.

1. **Odd commit subjects** (`Feat: x` uppercase, leading whitespace, empty subject, a merge commit `Merge pull request #5 ...`, subjects containing quotes, `$(...)`, backticks or newlines): expected behavior is a patch bump and the subject reproduced verbatim in the plan JSON, never a crash or a shell evaluation. Tests: `test_bump_level_non_conventional_is_patch` (Task 2), `test_plan_subject_with_shell_metacharacters_round_trips` and `test_plan_merge_commit_uses_first_parent_diff` (Task 8).
2. **A source file that is missing or unparsable at HEAD** (adopter typo in `file`, invalid JSON): expected behavior is a one-line `ConfigError`/`FormatError` naming the stream and file, exit code 1, no traceback. Tests: `test_plan_missing_source_at_head_is_config_error` (Task 8), `test_cli_error_prints_one_line_and_exits_1` (Task 8).
3. **A commit that touches a source file without changing its value** (reformat, comment edit, `prerelease` edit): expected behavior is that it is NOT the fold base and is itself folded as a normal commit. Test: `test_find_base_ignores_touch_without_value_change` (Task 8).
4. **A PR that introduces a brand-new stream** (source absent at the merge base): expected behavior is that `guard` skips that stream with a notice instead of failing the adopting PR. Test: `test_guard_skips_stream_whose_source_is_absent_at_base` (Task 10).
5. **A target regex that matches 0 or 2+ times, or a JSON path whose value is not a scalar string:** expected behavior is an error naming the file and the match count/path before anything is written. Tests: `test_regex_zero_matches_is_error`, `test_regex_two_matches_is_error`, `test_json_path_non_string_is_error` (Task 5).

---

## File Structure

Everything under the `ericfitz/version-bump-bot` repo root.

```
README.md                                   usage, config reference, adoption checklist (Task 14)
.gitignore                                  .venv/, __pycache__/, .pytest_cache/, .ruff_cache/, *.egg-info/, dist/, .local/, HANDOFF.md
ruff.toml                                   ruff config (line-length 100, py311)
pyproject.toml                              package metadata, scripts entry, pytest config, dev group
docs/superpowers/specs/2026-10-03-version-bump-bot-design.md  the spec (do not edit during implementation)
docs/superpowers/plans/2026-10-03-version-bump-bot.md        this plan
.github/version-bump.toml                   self-adoption config (Task 14)
.github/workflows/ci.yml                    CI: ruff, pytest, actionlint, tag-constant check (Task 1)
.github/workflows/bump.yml                  reusable: post-merge bump (Task 13)
.github/workflows/guard.yml                 reusable: PR guard (Task 13)
.github/workflows/release-alias.yml         tag-triggered: move the major alias v<MAJOR> (Task 13)
.github/workflows/version.yml               self-adoption caller (Task 14)
src/version_bump/
  __init__.py                               __version__ read from package metadata
  __main__.py                               `python -m version_bump`
  errors.py                                 VersionBumpError hierarchy
  semver.py                                 Version, Level, bump_level()
  pathglob.py                               `**`-aware glob matching for skip_paths and triggers
  config.py                                 TOML config -> frozen dataclasses, validation
  jsonpos.py                                locate a scalar's byte span in JSON text by dotted path
  formats.py                                read/write version for json-semver, json-path, toml-path, regex
  gitops.py                                 thin git wrappers (subprocess, stdin=DEVNULL)
  plan.py                                   fold base, triggers, bump fold, Plan dataclasses + JSON
  apply.py                                  write source + targets; run `after` hooks
  guard.py                                  base-vs-head value comparison; `verify` commands
  tags.py                                   render tag names; idempotent local tag creation
  doctor.py                                 repo-settings checks via injectable fetch; fix commands
  cli.py                                    argparse entry point
tests/
  conftest.py                               scratch repo fixture + helpers
  test_semver.py test_pathglob.py test_jsonpos.py test_formats.py test_config.py
  test_gitops.py test_plan.py test_apply.py test_guard.py test_tags.py test_doctor.py
  test_cli.py test_e2e.py test_workflows.py test_release_tag.py
  fixtures/doctor/*.json                    canned `gh api` responses
```

Interfaces that every task shares (defined in Tasks 2, 6 and 8; repeated here so a task can be read alone):

```python
# semver.py
Level = Literal["major", "minor", "patch"]
class Version:            # frozen dataclass(major:int, minor:int, patch:int)
    @classmethod parse(text: str) -> Version
    bump(level: Level) -> Version
    __str__() -> "X.Y.Z"
def bump_level(subject: str, breaking: Level) -> Level

# config.py
class FileSpec:  file: str; format: str; path: str | None; regex: str | None
class Trigger:   changed: tuple[str, ...]; ignore_json_paths: tuple[str, ...]
class Stream:    name: str; source: FileSpec; targets: tuple[FileSpec, ...]; trigger: Trigger | None
                 breaking: Level; tag: str | None; after: tuple[str, ...]; verify: tuple[str, ...]
class Config:    skip_paths: tuple[str, ...]; streams: tuple[Stream, ...]
def load_config(path: Path) -> Config

# plan.py  (the JSON contract between CLI invocations and the workflow)
{
  "ref": "<sha>", "base": "<sha>" | "WORKTREE",
  "pending": [{"commit": "<sha>", "subject": "...", "streams": ["server"]}],
  "streams": [{"name": "server", "from": "1.8.16", "to": "1.9.1", "tag": "v1.9.1" | null,
               "after": ["make generate-api"], "files": [".version", "api/version.go"]}],
  "commit_subject": "chore(version): bump server to 1.9.1",
  "commit_body": "Folds 3 merged commit(s):\n- abc1234 fix: one (#2)\n..."
}
```

`streams` lists only the streams that bump. `pending` lists every non-skipped first-parent commit after `base` (its `streams` may be empty when it triggers nothing). "Nothing to do" is `streams == []`.

---

### Task 1: Repo scaffold, uv/ruff/pytest config, CI workflow

**Files:**
- Create: `README.md`, `.gitignore`, `ruff.toml`
- Create: `pyproject.toml`
- Create: `src/version_bump/__init__.py`, `__main__.py`, `errors.py`, `cli.py`
- Create: `tests/test_cli.py`
- Create: `.github/workflows/ci.yml`

**Interfaces:**
- Produces: `version_bump.errors.VersionBumpError` (base), `ConfigError`, `FormatError`, `GitError`, `GuardError`, `TagError`, `HookError`; `version_bump.cli.main(argv: list[str] | None = None) -> int`.

- [ ] **Step 1: Write the package metadata and shared tooling config**

`pyproject.toml`:

```toml
[project]
name = "version-bump-bot"
version = "0.1.0"
description = "Post-merge semantic-version bump bot: one bump per merged PR, driven by config."
readme = "README.md"
requires-python = ">=3.11"
dependencies = []

[project.scripts]
version-bump = "version_bump.cli:main"

[build-system]
requires = ["uv_build>=0.8.0"]
build-backend = "uv_build"

[dependency-groups]
dev = ["pytest>=8.3", "ruff>=0.12"]

[tool.uv.build-backend]
module-name = "version_bump"   # the project is named version-bump-bot but the package is version_bump

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-q"
```

`ruff.toml` (repo root):

```toml
line-length = 100
target-version = "py311"

[lint]
select = ["E", "F", "I", "UP", "B", "W"]
ignore = ["E501"]   # the formatter owns line length; long TOML/shell string literals are legitimate
```

`.gitignore`:

```
.venv/
__pycache__/
.pytest_cache/
.ruff_cache/
*.egg-info/
dist/
.local/
HANDOFF.md
```

`README.md` (stub; Task 14 replaces it with the full adoption guide):

```markdown
# version-bump-bot

Post-merge semantic-version bump bot: one version increment per merged PR, driven by
`.github/version-bump.toml`, with no PR-time edits to version files. A Python CLI plus two
reusable GitHub Actions workflows (`bump.yml`, `guard.yml`); the GitHub App
`ericfitz-version-bump` is only an identity. Design: `docs/superpowers/specs/2026-10-03-version-bump-bot-design.md`.
```

- [ ] **Step 2: Write the package skeleton**

`src/version_bump/__init__.py`:

```python
"""version-bump-bot: post-merge semantic-version bumps driven by .github/version-bump.toml."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("version-bump-bot")
except PackageNotFoundError:  # running from a plain source checkout
    __version__ = "0.0.0"
```

`src/version_bump/__main__.py`:

```python
import sys

from version_bump.cli import main

sys.exit(main())
```

`src/version_bump/errors.py`:

```python
"""Error hierarchy. The CLI prints str(error) on one line and exits 1 for any of these."""


class VersionBumpError(Exception):
    """Base class for every expected failure."""


class ConfigError(VersionBumpError):
    """The config file is missing, malformed, or semantically invalid."""


class FormatError(VersionBumpError):
    """A version file cannot be read or written in its declared format."""


class GitError(VersionBumpError):
    """A git command failed."""


class GuardError(VersionBumpError):
    """The PR guard found a violation."""


class TagError(VersionBumpError):
    """A tag exists on a different commit."""


class HookError(VersionBumpError):
    """An `after` hook or `verify` command failed."""
```

`src/version_bump/cli.py` (stub; later tasks add subcommands):

```python
"""Command-line entry point: version-bump <subcommand>."""

from __future__ import annotations

import argparse
import sys

from version_bump import __version__
from version_bump.errors import VersionBumpError

DEFAULT_CONFIG = ".github/version-bump.toml"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="version-bump")
    parser.add_argument("--version", action="version", version=f"version-bump {__version__}")
    parser.add_argument("--repo", default=".", help="repository root (default: cwd)")
    parser.add_argument("--config", default=DEFAULT_CONFIG, help="config path relative to --repo")
    parser.add_subparsers(dest="command", metavar="<command>")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 2
    try:
        return args.func(args)
    except VersionBumpError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3: Write the smoke test**

`tests/test_cli.py`:

```python
import subprocess
import sys

from version_bump.cli import main


def test_no_command_prints_help_and_exits_2(capsys):
    assert main([]) == 2
    assert "usage: version-bump" in capsys.readouterr().out


def test_module_entry_point_runs():
    proc = subprocess.run(
        [sys.executable, "-m", "version_bump", "--version"],
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        check=False,
    )
    assert proc.returncode == 0
    assert proc.stdout.startswith("version-bump ")
```

- [ ] **Step 4: Run the tests and linters**

Run (from the repo root): `uv run pytest && uv run ruff check . && uv run ruff format --check .`
Expected: 2 passed; ruff clean. If `ruff format --check` reports files, run `uv run ruff format .` and re-check.

- [ ] **Step 5: Write the CI workflow**

`.github/workflows/ci.yml`:

```yaml
name: CI

on:
  pull_request:
    branches: [main]
  push:
    branches: [main]

permissions:
  contents: read

jobs:
  test:
    name: Lint and test
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
      - uses: astral-sh/setup-uv@v6
        with:
          python-version: "3.12"
      - name: Install actionlint
        working-directory: ${{ runner.temp }}
        run: |
          set -euo pipefail
          bash <(curl -fsSL https://raw.githubusercontent.com/rhysd/actionlint/main/scripts/download-actionlint.bash)
          echo "${{ runner.temp }}" >> "$GITHUB_PATH"
      - name: ruff check
        run: uv run ruff check .
      - name: ruff format
        run: uv run ruff format --check .
      - name: pytest (includes actionlint and release-tag checks)
        env:
          ACTIONLINT_REQUIRED: "1"
        run: uv run pytest
```

- [ ] **Step 6: Validate the workflow and commit**

Run: `actionlint .github/workflows/ci.yml`
Expected: no output (clean).

```bash
git add README.md .gitignore ruff.toml pyproject.toml src tests .github/workflows/ci.yml
git commit -m "chore: scaffold package, tooling and CI workflow"
```

---

### Task 2: Semantic version and bump-level parsing

**Files:**
- Create: `src/version_bump/semver.py`
- Test: `tests/test_semver.py`

**Interfaces:**
- Produces: `Level = Literal["major","minor","patch"]`; `Version(major, minor, patch)` frozen dataclass with `Version.parse(text) -> Version`, `.bump(level) -> Version`, `str(v) == "X.Y.Z"`; `bump_level(subject: str, breaking: Level) -> Level`; `VERSION_PREFIX_RE` (matches `X.Y.Z` at the start of a string, leaving any suffix such as `-rc1`).

- [ ] **Step 1: Write the failing tests** (ported from the bash prototype's `self-test` cases)

`tests/test_semver.py`:

```python
import pytest

from version_bump.errors import FormatError
from version_bump.semver import Version, bump_level


def test_parse_and_str():
    assert str(Version.parse("1.8.16")) == "1.8.16"
    assert Version.parse("1.8.16") == Version(1, 8, 16)


@pytest.mark.parametrize("bad", ["1.8", "v1.8.16", "1.8.16-rc1", "", "a.b.c", "01.2.3"])
def test_parse_rejects_non_semver(bad):
    with pytest.raises(FormatError):
        Version.parse(bad)


def test_bump_levels():
    v = Version(1, 8, 16)
    assert v.bump("patch") == Version(1, 8, 17)
    assert v.bump("minor") == Version(1, 9, 0)
    assert v.bump("major") == Version(2, 0, 0)


# Cases from scripts/ci-version-bump.sh self-test, server stream (breaking = minor).
@pytest.mark.parametrize(
    "subject,expected",
    [
        ("feat: add widget export", "minor"),
        ("feat(scope)!: breaking widget rewrite", "minor"),
        ("fix: correct widget off-by-one", "patch"),
        ("chore(deps): bump golang.org/x/net", "patch"),
        ("feat(api): add pagination cursor", "minor"),
        ("docs: update readme", "patch"),
        ("refactor(auth): simplify token check", "patch"),
    ],
)
def test_bump_level_breaking_minor(subject, expected):
    assert bump_level(subject, "minor") == expected


# Cases from the schema stream (breaking = major).
@pytest.mark.parametrize(
    "subject,expected",
    [
        ("fix: typo", "patch"),
        ("feat: add endpoint", "minor"),
        ("feat(api)!: breaking rewrite", "major"),
        ("fix: patch bump", "patch"),
        ("chore!: breaking chore", "major"),
    ],
)
def test_bump_level_breaking_major(subject, expected):
    assert bump_level(subject, "major") == expected


@pytest.mark.parametrize(
    "subject",
    ["Feat: capitalised type", "  fix: leading space", "", "Merge pull request #5 from x/y", "feat"],
)
def test_bump_level_non_conventional_is_patch(subject):
    assert bump_level(subject, "major") == "patch"


def test_fold_sequence_matches_prototype():
    # fix + feat + fix on 1.8.16 -> 1.9.1 (prototype case "fold of fix+feat(schema)+fix")
    v = Version.parse("1.8.16")
    for subject in ["fix: one (#2)", "feat(api): add b (#3)", "fix: two (#4)"]:
        v = v.bump(bump_level(subject, "minor"))
    assert str(v) == "1.9.1"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_semver.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'version_bump.semver'`.

- [ ] **Step 3: Implement semver.py**

```python
"""Semantic versions and the conventional-commit bump rule (spec: Bump rules, item 4)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from version_bump.errors import FormatError

Level = Literal["major", "minor", "patch"]
LEVELS: tuple[Level, ...] = ("major", "minor", "patch")

# Exactly X.Y.Z, no leading zeros, no prefix or suffix.
SEMVER_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
# X.Y.Z at the start of a string; whatever follows (e.g. "-rc1") is a suffix to preserve.
VERSION_PREFIX_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)")

FEAT_RE = re.compile(r"^feat(\(.+\))?!?:")
BREAKING_RE = re.compile(r"^[a-z]+(\(.+\))?!:")


@dataclass(frozen=True, order=True)
class Version:
    major: int
    minor: int
    patch: int

    @classmethod
    def parse(cls, text: str) -> Version:
        m = SEMVER_RE.match(text)
        if not m:
            raise FormatError(f"not a MAJOR.MINOR.PATCH version: {text!r}")
        return cls(int(m.group(1)), int(m.group(2)), int(m.group(3)))

    def bump(self, level: Level) -> Version:
        if level == "major":
            return Version(self.major + 1, 0, 0)
        if level == "minor":
            return Version(self.major, self.minor + 1, 0)
        return Version(self.major, self.minor, self.patch + 1)

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"


def bump_level(subject: str, breaking: Level) -> Level:
    """Bump level for one commit subject (= squash-merge PR title).

    `^[a-z]+(\\(.+\\))?!:` -> the stream's breaking level; `^feat(\\(.+\\))?!?:` -> minor;
    anything else -> patch. A subject with both feat and `!` gets the breaking level.
    """
    if BREAKING_RE.match(subject):
        return breaking
    if FEAT_RE.match(subject):
        return "minor"
    return "patch"
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_semver.py && uv run ruff check . && uv run ruff format --check .`
Expected: all passed, ruff clean.

- [ ] **Step 5: Commit**

```bash
git add src/version_bump/semver.py tests/test_semver.py
git commit -m "feat(semver): add Version and conventional-subject bump level"
```

---

### Task 3: Path glob matching for skip_paths and triggers

**Files:**
- Create: `src/version_bump/pathglob.py`
- Test: `tests/test_pathglob.py`

**Interfaces:**
- Produces: `matches(pattern: str, path: str) -> bool`, `matches_any(patterns: Iterable[str], path: str) -> bool`, `all_match(patterns: Iterable[str], paths: Iterable[str]) -> bool` (empty `paths` -> `True`, matching the prototype's `is-docs-only` with no args).

Semantics (gitignore-like, applied to repo-relative paths with `/` separators): `**` matches zero or more whole path segments, `*` matches any run of characters except `/`, `?` matches one character except `/`; a pattern without `/` and without `**` still only matches a whole path (so `*.md` matches `README.md` but not `docs/a.md`; use `**/*.md` for "any depth"). `fnmatch` is NOT used because its `*` crosses `/` and it has no `**`.

- [ ] **Step 1: Write the failing tests**

`tests/test_pathglob.py`:

```python
import pytest

from version_bump.pathglob import all_match, matches, matches_any

SKIP = ["docs/**", "PROGRESS.md", "**/*.md"]


@pytest.mark.parametrize(
    "pattern,path,expected",
    [
        ("docs/**", "docs/a.md", True),
        ("docs/**", "docs/sub/deep/x.txt", True),
        ("docs/**", "docs", False),
        ("docs/**", "api/docs/a.md", False),
        ("**/*.md", "README.md", True),  # zero leading segments
        ("**/*.md", "docs/superpowers/specs/2026-01-01-x.md", True),
        ("**/*.md", "README.mdx", False),
        ("*.md", "README.md", True),
        ("*.md", "docs/a.md", False),  # `*` does not cross `/`
        ("PROGRESS.md", "PROGRESS.md", True),
        ("PROGRESS.md", "sub/PROGRESS.md", False),
        ("api-schema/tmi-openapi.json", "api-schema/tmi-openapi.json", True),
        ("src/**", "src/version_bump/cli.py", True),
        (".github/workflows/bump*", ".github/workflows/bump.yml", True),
        (".github/workflows/bump*", ".github/workflows/version.yml", False),
        ("src/?.py", "src/a.py", True),
        ("src/?.py", "src/ab.py", False),
        ("a/**/b", "a/b", True),
        ("a/**/b", "a/x/y/b", True),
        ("a.b", "aXb", False),  # regex metacharacters are escaped
    ],
)
def test_matches(pattern, path, expected):
    assert matches(pattern, path) is expected


def test_matches_any():
    assert matches_any(SKIP, "docs/foo.md")
    assert not matches_any(SKIP, "api/version.go")


# Ported from the prototype's is-docs-only self-test cases.
def test_all_match_docs_only_cases():
    assert all_match(SKIP, ["docs/foo.md", "PROGRESS.md", "README.md"])
    assert all_match(SKIP, ["docs/superpowers/specs/2026-01-01-x.md"])
    assert not all_match(SKIP, ["docs/foo.md", "api/version.go"])
    assert not all_match(SKIP, ["api-schema/tmi-openapi.json"])
    assert all_match(SKIP, [])  # nothing non-doc changed


def test_all_match_with_no_patterns_is_false_unless_empty():
    assert not all_match([], ["x"])
    assert all_match([], [])
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_pathglob.py`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement pathglob.py**

```python
"""`**`-aware glob matching for repo-relative paths (skip_paths, trigger.changed)."""

from __future__ import annotations

import re
from collections.abc import Iterable
from functools import lru_cache


@lru_cache(maxsize=256)
def compile_glob(pattern: str) -> re.Pattern[str]:
    out: list[str] = []
    i = 0
    n = len(pattern)
    while i < n:
        c = pattern[i]
        if c == "*":
            if pattern.startswith("**", i):
                i += 2
                if i < n and pattern[i] == "/":
                    # "**/" : zero or more whole segments including the trailing slash
                    out.append("(?:.*/)?")
                    i += 1
                else:
                    # trailing "**" or "**x": anything at all
                    out.append(".*")
            else:
                out.append("[^/]*")
                i += 1
        elif c == "?":
            out.append("[^/]")
            i += 1
        elif c == "/" and pattern.startswith("/**", i) and i + 3 == n:
            # "a/**" : "a/" followed by at least one character
            out.append("/.+")
            i += 3
        else:
            out.append(re.escape(c))
            i += 1
    return re.compile("^" + "".join(out) + "$")


def matches(pattern: str, path: str) -> bool:
    return compile_glob(pattern).match(path) is not None


def matches_any(patterns: Iterable[str], path: str) -> bool:
    return any(matches(p, path) for p in patterns)


def all_match(patterns: Iterable[str], paths: Iterable[str]) -> bool:
    """True when every path matches some pattern. An empty path list is vacuously True."""
    pats = tuple(patterns)
    return all(matches_any(pats, p) for p in paths)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_pathglob.py && uv run ruff check . && uv run ruff format --check .`
Expected: all passed. If `("docs/**", "docs", False)` fails, the `/**`-at-end branch is not being hit; check that the branch precedes the generic `*` handling for the slash character (it keys on `/`, not `*`).

- [ ] **Step 5: Commit**

```bash
git add src/version_bump/pathglob.py tests/test_pathglob.py
git commit -m "feat(pathglob): add **-aware glob matching for skip paths and triggers"
```

---

### Task 4: JSON scalar position locator (for byte-preserving JSON writes)

**Files:**
- Create: `src/version_bump/jsonpos.py`
- Test: `tests/test_jsonpos.py`

**Interfaces:**
- Produces: `locate_json_value(text: str, path: str) -> tuple[int, int]` returning the `[start, end)` span of the scalar token (for strings: including both quotes) at dotted `path` (e.g. `info.version`, `major`); raises `FormatError` when the document is invalid, the path is missing, or the value is an object/array. `split_path(path) -> list[str]`. Also `delete_json_paths(obj, paths: Iterable[str]) -> Any` used by triggers (removes dotted paths from a parsed object; missing paths are ignored).

Why: `json.dumps` would reorder/reformat; the writer (Task 5) replaces just the token span. Dotted paths index objects only (array indices are out of scope for v1; a numeric segment is looked up as an object key).

- [ ] **Step 1: Write the failing tests**

`tests/test_jsonpos.py`:

```python
import json

import pytest

from version_bump.errors import FormatError
from version_bump.jsonpos import delete_json_paths, locate_json_value

DOC = '{\n  "info": {"title": "x", "version": "2.3.1"},\n  "major": 1, "paths": {"/a": {}}\n}\n'


def test_locate_nested_string():
    s, e = locate_json_value(DOC, "info.version")
    assert DOC[s:e] == '"2.3.1"'


def test_locate_top_level_number():
    s, e = locate_json_value(DOC, "major")
    assert DOC[s:e] == "1"


def test_escaped_quotes_and_braces_in_strings_do_not_confuse_scanner():
    doc = '{"a": "}{\\"version\\": 9", "version": "1.0.0"}'
    s, e = locate_json_value(doc, "version")
    assert doc[s:e] == '"1.0.0"'


def test_same_key_elsewhere_is_not_matched():
    doc = '{"x": {"version": "9.9.9"}, "info": {"version": "1.2.3"}}'
    s, e = locate_json_value(doc, "info.version")
    assert doc[s:e] == '"1.2.3"'


def test_crlf_and_tabs_preserved_positions():
    doc = '{\r\n\t"version":\t"1.2.3"\r\n}\r\n'
    s, e = locate_json_value(doc, "version")
    assert doc[s:e] == '"1.2.3"'


def test_missing_path_is_error():
    with pytest.raises(FormatError, match="info.nope"):
        locate_json_value(DOC, "info.nope")


def test_non_scalar_is_error():
    with pytest.raises(FormatError, match="not a scalar"):
        locate_json_value(DOC, "info")


def test_invalid_json_is_error():
    with pytest.raises(FormatError, match="invalid JSON"):
        locate_json_value("{", "a")


def test_delete_json_paths():
    obj = json.loads(DOC)
    out = delete_json_paths(obj, ["info.version", "missing.path", "major"])
    assert out == {"info": {"title": "x"}, "paths": {"/a": {}}}
    assert "version" in json.loads(DOC)["info"]  # input not mutated
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_jsonpos.py`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement jsonpos.py**

```python
"""Locate a scalar's byte span in JSON text by dotted path, without re-serialising."""

from __future__ import annotations

import copy
import json
from collections.abc import Iterable
from typing import Any

from version_bump.errors import FormatError

_WS = " \t\r\n"


def split_path(path: str) -> list[str]:
    parts = path.split(".")
    if not path or any(p == "" for p in parts):
        raise FormatError(f"invalid JSON path {path!r}")
    return parts


def delete_json_paths(obj: Any, paths: Iterable[str]) -> Any:
    """Return a deep copy of obj with each dotted path removed (missing paths ignored)."""
    out = copy.deepcopy(obj)
    for path in paths:
        parts = split_path(path)
        node = out
        for key in parts[:-1]:
            if not isinstance(node, dict) or key not in node:
                node = None
                break
            node = node[key]
        if isinstance(node, dict):
            node.pop(parts[-1], None)
    return out


class _Scanner:
    def __init__(self, text: str) -> None:
        self.text = text
        self.i = 0

    def skip_ws(self) -> None:
        while self.i < len(self.text) and self.text[self.i] in _WS:
            self.i += 1

    def scan_string(self) -> tuple[int, int, str]:
        """At an opening quote: return (start, end, decoded value)."""
        start = self.i
        assert self.text[self.i] == '"'
        self.i += 1
        while self.i < len(self.text):
            c = self.text[self.i]
            if c == "\\":
                self.i += 2
                continue
            if c == '"':
                self.i += 1
                return start, self.i, json.loads(self.text[start : self.i])
            self.i += 1
        raise FormatError("invalid JSON: unterminated string")

    def scan_scalar(self) -> tuple[int, int]:
        start = self.i
        while self.i < len(self.text) and self.text[self.i] not in _WS + ",]}":
            self.i += 1
        return start, self.i

    def skip_value(self) -> None:
        self.skip_ws()
        c = self.text[self.i]
        if c == '"':
            self.scan_string()
        elif c == "{":
            self.skip_container("{", "}")
        elif c == "[":
            self.skip_container("[", "]")
        else:
            self.scan_scalar()

    def skip_container(self, open_ch: str, close_ch: str) -> None:
        depth = 0
        while self.i < len(self.text):
            c = self.text[self.i]
            if c == '"':
                self.scan_string()
                continue
            if c == open_ch:
                depth += 1
            elif c == close_ch:
                depth -= 1
                if depth == 0:
                    self.i += 1
                    return
            self.i += 1
        raise FormatError("invalid JSON: unterminated container")

    def find(self, parts: list[str], path: str) -> tuple[int, int]:
        """Descend into the object at self.i following parts; return the scalar's span."""
        self.skip_ws()
        if self.i >= len(self.text) or self.text[self.i] != "{":
            raise FormatError(f"JSON path {path!r} not found: expected an object")
        self.i += 1
        want = parts[0]
        while True:
            self.skip_ws()
            if self.i >= len(self.text):
                raise FormatError("invalid JSON: unterminated object")
            if self.text[self.i] == "}":
                raise FormatError(f"JSON path {path!r} not found")
            if self.text[self.i] == ",":
                self.i += 1
                continue
            _, _, key = self.scan_string()
            self.skip_ws()
            if self.text[self.i] != ":":
                raise FormatError("invalid JSON: expected ':'")
            self.i += 1
            self.skip_ws()
            if key != want:
                self.skip_value()
                continue
            if len(parts) == 1:
                c = self.text[self.i]
                if c in "{[":
                    raise FormatError(f"JSON path {path!r} is not a scalar")
                if c == '"':
                    s, e, _ = self.scan_string()
                    return s, e
                return self.scan_scalar()
            return self.find(parts[1:], path)


def locate_json_value(text: str, path: str) -> tuple[int, int]:
    try:
        json.loads(text)
    except json.JSONDecodeError as exc:
        raise FormatError(f"invalid JSON: {exc.msg} at line {exc.lineno}") from None
    return _Scanner(text).find(split_path(path), path)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_jsonpos.py && uv run ruff check . && uv run ruff format --check .`
Expected: all passed.

- [ ] **Step 5: Commit**

```bash
git add src/version_bump/jsonpos.py tests/test_jsonpos.py
git commit -m "feat(jsonpos): locate scalar spans in JSON text for byte-preserving writes"
```

---

### Task 5: Format readers and writers (json-semver, json-path, toml-path, regex)

**Files:**
- Create: `src/version_bump/formats.py`
- Test: `tests/test_formats.py`

**Interfaces:**
- Consumes: `Version`, `VERSION_PREFIX_RE` (Task 2); `locate_json_value` (Task 4).
- Produces:
  - `FileSpec(file: str, format: str, path: str | None = None, regex: str | None = None)` frozen dataclass (this task defines it; Task 6's config builds it). `FORMATS = ("json-semver", "json-path", "toml-path", "regex")`.
  - `Captured(major: int | None, minor: int | None, patch: int | None)` with `.matches(v: Version) -> bool` (compares only the captured components) and `.text` property (`"1.?.3"` style, for messages).
  - `read_full(text: str, spec: FileSpec) -> Version` for sources (all three components required).
  - `read_partial(text: str, spec: FileSpec) -> Captured` for targets (a regex may capture a subset).
  - `write_version(text: str, spec: FileSpec, version: Version) -> str` (new file text; only the version digits change).
  - `validate_spec(spec: FileSpec, role: str) -> None` raises `ConfigError` for a malformed spec (`role` is `"source"` or `"target"`; a source regex must capture all of major/minor/patch or `version`).

Format rules (spec: Formats (v1)):
- `json-semver`: object with integer `major`, `minor`, `patch`; other fields (e.g. `prerelease`) preserved byte-for-byte. `path` may name a nested object (default: the root).
- `json-path`: dotted path to a string starting `X.Y.Z`; any suffix after the digits (`-rc1`) is kept.
- `toml-path`: dotted path `table.sub.key`; the writer scans lines, tracks `[table]` headers, and replaces the digits inside the quoted value of `key = "..."` in that table. Dotted-key forms (`project.version = "1.0.0"` at top level) and inline tables are errors (`FormatError`). `tomllib` validates on read.
- `regex`: Python `re` pattern compiled with `re.MULTILINE`; must match exactly once (`finditer` count == 1); named groups are either `version` (holding `X.Y.Z`) or a subset of `major`/`minor`/`patch`. The writer replaces the matched group spans right-to-left.

- [ ] **Step 1: Write the failing tests**

`tests/test_formats.py`:

```python
import pytest

from version_bump.errors import ConfigError, FormatError
from version_bump.formats import Captured, FileSpec, read_full, read_partial, validate_spec, write_version
from version_bump.semver import Version

V = Version(1, 9, 1)

JSON_SEMVER = '{\n  "major": 1,\n  "minor": 8,\n  "patch": 16,\n  "prerelease": ""\n}\n'
OPENAPI = '{"info": {"version": "2.3.1", "title": "x"}, "paths": {"/a": {}}}\n'
PYPROJECT = '[project]\nname = "x"\nversion = "0.1.0"\n\n[tool.other]\nversion = "9.9.9"\n'
GO = (
    "package api\n\nconst (\n\tVersionMajor = \"1\"\n\tVersionMinor = \"8\"\n"
    "\tVersionPatch = \"16\"\n\tVersionPreRelease = \"\"\n)\n"
)
WORKFLOW = "env:\n  VERSION_BUMP_BOT_REF: v0.1.0\n  OTHER: v0.1.0\n"


def spec(fmt, **kw):
    return FileSpec(file="f", format=fmt, path=kw.get("path"), regex=kw.get("regex"))


# --- json-semver ---------------------------------------------------------------
def test_json_semver_round_trip_preserves_bytes():
    s = spec("json-semver")
    assert read_full(JSON_SEMVER, s) == Version(1, 8, 16)
    out = write_version(JSON_SEMVER, s, V)
    assert out == '{\n  "major": 1,\n  "minor": 9,\n  "patch": 1,\n  "prerelease": ""\n}\n'
    assert read_full(out, s) == V


def test_json_semver_missing_field_is_error():
    with pytest.raises(FormatError, match="patch"):
        read_full('{"major": 1, "minor": 2}', spec("json-semver"))


def test_json_semver_non_integer_is_error():
    with pytest.raises(FormatError, match="integer"):
        read_full('{"major": "1", "minor": 2, "patch": 3}', spec("json-semver"))


# --- json-path -----------------------------------------------------------------
def test_json_path_round_trip_preserves_bytes_and_suffix():
    s = spec("json-path", path="info.version")
    assert read_full(OPENAPI, s) == Version(2, 3, 1)
    out = write_version(OPENAPI, s, Version(2, 4, 0))
    assert out == OPENAPI.replace("2.3.1", "2.4.0")
    pre = '{"version": "1.2.3-rc1"}'
    assert write_version(pre, spec("json-path", path="version"), V) == '{"version": "1.9.1-rc1"}'


def test_json_path_crlf_preserved():
    doc = '{\r\n  "version": "1.2.3"\r\n}\r\n'
    assert write_version(doc, spec("json-path", path="version"), V) == doc.replace("1.2.3", "1.9.1")


def test_json_path_non_string_is_error():
    with pytest.raises(FormatError, match="string"):
        read_full('{"version": 123}', spec("json-path", path="version"))


def test_json_path_bad_version_is_error():
    with pytest.raises(FormatError, match="MAJOR.MINOR.PATCH"):
        read_full('{"version": "v1.2"}', spec("json-path", path="version"))


# --- toml-path -----------------------------------------------------------------
def test_toml_path_round_trip_is_line_preserving():
    s = spec("toml-path", path="project.version")
    assert read_full(PYPROJECT, s) == Version(0, 1, 0)
    out = write_version(PYPROJECT, s, V)
    assert out == PYPROJECT.replace('version = "0.1.0"', 'version = "1.9.1"')
    assert 'version = "9.9.9"' in out  # the other table is untouched
    assert read_full(out, s) == V


def test_toml_path_wrong_table_is_error():
    with pytest.raises(FormatError, match="tool.nope.version"):
        read_full(PYPROJECT, spec("toml-path", path="tool.nope.version"))


def test_toml_path_dotted_key_form_is_error_on_write():
    doc = 'project.version = "0.1.0"\n'
    with pytest.raises(FormatError, match="exactly one"):
        write_version(doc, spec("toml-path", path="project.version"), V)


def test_toml_path_single_quoted_value():
    doc = "[project]\nversion = '0.1.0'\n"
    assert write_version(doc, spec("toml-path", path="project.version"), V) == "[project]\nversion = '1.9.1'\n"


# --- regex ---------------------------------------------------------------------
def test_regex_partial_targets_read_and_write():
    major = spec("regex", regex=r'VersionMajor = "(?P<major>\d+)"')
    minor = spec("regex", regex=r'VersionMinor = "(?P<minor>\d+)"')
    patch = spec("regex", regex=r'VersionPatch = "(?P<patch>\d+)"')
    assert read_partial(GO, major) == Captured(1, None, None)
    assert read_partial(GO, patch) == Captured(None, None, 16)
    out = GO
    for s in (major, minor, patch):
        out = write_version(out, s, V)
    assert 'VersionMajor = "1"' in out and 'VersionMinor = "9"' in out and 'VersionPatch = "1"' in out
    assert 'VersionPreRelease = ""' in out
    assert out.count("\n") == GO.count("\n")


def test_regex_version_group_read_full_and_write():
    s = spec("regex", regex=r"VERSION_BUMP_BOT_REF: v(?P<version>\d+\.\d+\.\d+)")
    assert read_full(WORKFLOW, s) == Version(0, 1, 0)
    assert write_version(WORKFLOW, s, V) == "env:\n  VERSION_BUMP_BOT_REF: v1.9.1\n  OTHER: v0.1.0\n"


def test_regex_zero_matches_is_error():
    with pytest.raises(FormatError, match="matched 0 times"):
        read_partial(GO, spec("regex", regex=r'Nope = "(?P<major>\d+)"'))


def test_regex_two_matches_is_error():
    with pytest.raises(FormatError, match="matched 2 times"):
        read_partial(WORKFLOW, spec("regex", regex=r"v(?P<version>\d+\.\d+\.\d+)"))


def test_regex_partial_source_is_error():
    with pytest.raises(FormatError, match="minor"):
        read_full(GO, spec("regex", regex=r'VersionMajor = "(?P<major>\d+)"'))


def test_captured_matches_only_captured_components():
    assert Captured(1, None, None).matches(Version(1, 5, 5))
    assert not Captured(1, None, 3).matches(Version(1, 5, 5))
    assert Captured(None, None, None).text == "?.?.?"
    assert Captured(1, None, 3).text == "1.?.3"


# --- validate_spec -------------------------------------------------------------
@pytest.mark.parametrize(
    "s,role,msg",
    [
        (spec("nope"), "source", "unknown format"),
        (spec("json-path"), "source", "requires 'path'"),
        (spec("toml-path"), "target", "requires 'path'"),
        (spec("regex"), "source", "requires 'regex'"),
        (spec("regex", regex="("), "source", "invalid regex"),
        (spec("regex", regex="x"), "target", "named group"),
        (spec("regex", regex=r"(?P<version>\d+)(?P<major>\d+)"), "target", "either 'version'"),
        (spec("regex", regex=r"(?P<major>\d+)"), "source", "all of major, minor and patch"),
    ],
)
def test_validate_spec_errors(s, role, msg):
    with pytest.raises(ConfigError, match=msg):
        validate_spec(s, role)


def test_validate_spec_ok():
    validate_spec(spec("json-semver"), "source")
    validate_spec(spec("regex", regex=r"(?P<major>\d+)"), "target")
    validate_spec(spec("regex", regex=r"(?P<version>\d+\.\d+\.\d+)"), "source")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_formats.py`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement formats.py**

```python
"""Read and write the version in each supported file format, preserving every other byte."""

from __future__ import annotations

import json
import re
import tomllib
from dataclasses import dataclass

from version_bump.errors import ConfigError, FormatError
from version_bump.jsonpos import locate_json_value, split_path
from version_bump.semver import VERSION_PREFIX_RE, Version

FORMATS = ("json-semver", "json-path", "toml-path", "regex")
_COMPONENTS = ("major", "minor", "patch")


@dataclass(frozen=True)
class FileSpec:
    file: str
    format: str
    path: str | None = None
    regex: str | None = None


@dataclass(frozen=True)
class Captured:
    major: int | None
    minor: int | None
    patch: int | None

    def matches(self, v: Version) -> bool:
        return all(
            getattr(self, c) is None or getattr(self, c) == getattr(v, c) for c in _COMPONENTS
        )

    @property
    def text(self) -> str:
        return ".".join("?" if getattr(self, c) is None else str(getattr(self, c)) for c in _COMPONENTS)

    def full(self, where: str) -> Version:
        missing = [c for c in _COMPONENTS if getattr(self, c) is None]
        if missing:
            raise FormatError(f"{where}: version component(s) not captured: {', '.join(missing)}")
        return Version(self.major, self.minor, self.patch)  # type: ignore[arg-type]


# --- validation ----------------------------------------------------------------
def _regex_groups(pattern: str) -> set[str]:
    try:
        return set(re.compile(pattern, re.MULTILINE).groupindex)
    except re.error as exc:
        raise ConfigError(f"invalid regex {pattern!r}: {exc}") from None


def validate_spec(spec: FileSpec, role: str) -> None:
    where = f"{role} {spec.file}"
    if spec.format not in FORMATS:
        raise ConfigError(f"{where}: unknown format {spec.format!r} (expected one of {FORMATS})")
    if spec.format in ("json-path", "toml-path"):
        if not spec.path:
            raise ConfigError(f"{where}: format {spec.format} requires 'path'")
        split_path(spec.path)
    if spec.format == "regex":
        if not spec.regex:
            raise ConfigError(f"{where}: format regex requires 'regex'")
        groups = _regex_groups(spec.regex)
        known = groups & ({"version"} | set(_COMPONENTS))
        if not known:
            raise ConfigError(f"{where}: regex needs a named group 'version' or major/minor/patch")
        if "version" in groups and groups & set(_COMPONENTS):
            raise ConfigError(f"{where}: regex uses either 'version' or major/minor/patch, not both")
        if role == "source" and "version" not in groups and not set(_COMPONENTS) <= groups:
            raise ConfigError(f"{where}: a source regex must capture all of major, minor and patch")


# --- helpers -------------------------------------------------------------------
def _prefix(where: str, value: str) -> tuple[Version, str]:
    m = VERSION_PREFIX_RE.match(value)
    if not m:
        raise FormatError(f"{where}: {value!r} does not start with MAJOR.MINOR.PATCH")
    return Version(int(m.group(1)), int(m.group(2)), int(m.group(3))), value[m.end() :]


def _json_load(where: str, text: str):
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise FormatError(f"{where}: invalid JSON: {exc.msg} at line {exc.lineno}") from None


def _walk(where: str, obj, path: str | None):
    node = obj
    for key in split_path(path) if path else []:
        if not isinstance(node, dict) or key not in node:
            raise FormatError(f"{where}: JSON path {path!r} not found")
        node = node[key]
    return node


# --- json-semver ---------------------------------------------------------------
def _read_json_semver(where: str, text: str, spec: FileSpec) -> Version:
    node = _walk(where, _json_load(where, text), spec.path)
    if not isinstance(node, dict):
        raise FormatError(f"{where}: json-semver expects an object")
    vals = []
    for c in _COMPONENTS:
        if c not in node:
            raise FormatError(f"{where}: json-semver object lacks {c!r}")
        if not isinstance(node[c], int) or isinstance(node[c], bool):
            raise FormatError(f"{where}: json-semver {c!r} must be an integer")
        vals.append(node[c])
    return Version(*vals)


def _write_json_semver(where: str, text: str, spec: FileSpec, v: Version) -> str:
    _read_json_semver(where, text, spec)
    out = text
    # Replace right-to-left so earlier spans stay valid.
    spans = []
    for c in _COMPONENTS:
        p = f"{spec.path}.{c}" if spec.path else c
        spans.append((locate_json_value(text, p), getattr(v, c)))
    for (s, e), val in sorted(spans, reverse=True):
        out = out[:s] + str(val) + out[e:]
    return out


# --- json-path -----------------------------------------------------------------
def _read_json_path(where: str, text: str, spec: FileSpec) -> Version:
    node = _walk(where, _json_load(where, text), spec.path)
    if not isinstance(node, str):
        raise FormatError(f"{where}: JSON path {spec.path!r} must be a string")
    return _prefix(where, node)[0]


def _write_json_path(where: str, text: str, spec: FileSpec, v: Version) -> str:
    _read_json_path(where, text, spec)
    s, e = locate_json_value(text, spec.path or "")
    old = json.loads(text[s:e])
    _, suffix = _prefix(where, old)
    return text[:s] + json.dumps(f"{v}{suffix}") + text[e:]


# --- toml-path -----------------------------------------------------------------
_TOML_HEADER = re.compile(r"^\s*\[\s*([^\]]+?)\s*\]\s*(?:#.*)?$")


def _toml_key_re(key: str) -> re.Pattern[str]:
    k = re.escape(key)
    return re.compile(rf'^(\s*(?:{k}|"{k}"|\'{k}\')\s*=\s*["\'])(\d+\.\d+\.\d+)')


def _read_toml_path(where: str, text: str, spec: FileSpec) -> Version:
    try:
        obj = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise FormatError(f"{where}: invalid TOML: {exc}") from None
    node = obj
    for key in split_path(spec.path or ""):
        if not isinstance(node, dict) or key not in node:
            raise FormatError(f"{where}: TOML path {spec.path!r} not found")
        node = node[key]
    if not isinstance(node, str):
        raise FormatError(f"{where}: TOML path {spec.path!r} must be a string")
    return _prefix(where, node)[0]


def _write_toml_path(where: str, text: str, spec: FileSpec, v: Version) -> str:
    _read_toml_path(where, text, spec)
    parts = split_path(spec.path or "")
    table, key = ".".join(parts[:-1]), parts[-1]
    key_re = _toml_key_re(key)
    lines = text.splitlines(keepends=True)
    current = ""
    hits: list[int] = []
    for i, line in enumerate(lines):
        h = _TOML_HEADER.match(line)
        if h:
            current = ".".join(p.strip().strip('"').strip("'") for p in h.group(1).split("."))
            continue
        if current == table and key_re.match(line):
            hits.append(i)
    if len(hits) != 1:
        raise FormatError(
            f"{where}: expected exactly one line 'key = \"X.Y.Z\"' for {spec.path!r} "
            f"in table [{table}], found {len(hits)} (dotted keys and inline tables are unsupported)"
        )
    i = hits[0]
    lines[i] = key_re.sub(lambda m: m.group(1) + str(v), lines[i], count=1)
    return "".join(lines)


# --- regex ---------------------------------------------------------------------
def _single_match(where: str, text: str, pattern: str) -> re.Match[str]:
    ms = list(re.finditer(pattern, text, re.MULTILINE))
    if len(ms) != 1:
        raise FormatError(f"{where}: regex {pattern!r} matched {len(ms)} times, expected exactly 1")
    return ms[0]


def _read_regex(where: str, text: str, spec: FileSpec) -> Captured:
    m = _single_match(where, text, spec.regex or "")
    if "version" in m.groupdict():
        v, _ = _prefix(where, m.group("version"))
        return Captured(v.major, v.minor, v.patch)
    vals = {}
    for c in _COMPONENTS:
        g = m.groupdict().get(c)
        vals[c] = int(g) if g is not None else None
    return Captured(vals["major"], vals["minor"], vals["patch"])


def _write_regex(where: str, text: str, spec: FileSpec, v: Version) -> str:
    m = _single_match(where, text, spec.regex or "")
    repl: list[tuple[int, int, str]] = []
    if "version" in m.groupdict():
        repl.append((m.start("version"), m.end("version"), str(v)))
    else:
        for c in _COMPONENTS:
            if m.groupdict().get(c) is not None:
                repl.append((m.start(c), m.end(c), str(getattr(v, c))))
    out = text
    for s, e, val in sorted(repl, reverse=True):
        out = out[:s] + val + out[e:]
    return out


# --- public API ----------------------------------------------------------------
def read_partial(text: str, spec: FileSpec) -> Captured:
    where = spec.file
    if spec.format == "regex":
        return _read_regex(where, text, spec)
    v = read_full(text, spec)
    return Captured(v.major, v.minor, v.patch)


def read_full(text: str, spec: FileSpec) -> Version:
    where = spec.file
    if spec.format == "json-semver":
        return _read_json_semver(where, text, spec)
    if spec.format == "json-path":
        return _read_json_path(where, text, spec)
    if spec.format == "toml-path":
        return _read_toml_path(where, text, spec)
    if spec.format == "regex":
        return _read_regex(where, text, spec).full(where)
    raise ConfigError(f"{where}: unknown format {spec.format!r}")


def write_version(text: str, spec: FileSpec, version: Version) -> str:
    where = spec.file
    if spec.format == "json-semver":
        return _write_json_semver(where, text, spec, version)
    if spec.format == "json-path":
        return _write_json_path(where, text, spec, version)
    if spec.format == "toml-path":
        return _write_toml_path(where, text, spec, version)
    if spec.format == "regex":
        return _write_regex(where, text, spec, version)
    raise ConfigError(f"{where}: unknown format {spec.format!r}")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_formats.py && uv run ruff check . && uv run ruff format --check .`
Expected: all passed. Note `test_toml_path_dotted_key_form_is_error_on_write`: `tomllib` parses `project.version = ...` fine (read succeeds), but the line scanner finds 0 lines under `[project]`, which is the intended error.

- [ ] **Step 5: Commit**

```bash
git add src/version_bump/formats.py tests/test_formats.py
git commit -m "feat(formats): add byte-preserving readers and writers for the four formats"
```

---

### Task 6: Config loading and validation

**Files:**
- Create: `src/version_bump/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: `FileSpec`, `validate_spec` (Task 5); `Level`, `LEVELS` (Task 2); `compile_glob` (Task 3).
- Produces: `Trigger(changed, ignore_json_paths)`, `Stream(name, source, targets, trigger, breaking, tag, after, verify)`, `Config(skip_paths, streams)` frozen dataclasses; `parse_config(text: str, where: str = "config") -> Config`; `load_config(path: Path) -> Config` (raises `ConfigError` when missing); `DEFAULT_CONFIG_PATH = ".github/version-bump.toml"`; `Config.stream(name) -> Stream` (KeyError-free: raises `ConfigError`).

Validation rules: `[merge].skip_paths` defaults to `[]`; at least one `[[stream]]`; `name` required, unique, matching `^[A-Za-z0-9._-]+$`; `source` is a table with `file` and `format` (+ `path`/`regex` per format); `targets` default `[]`, each a table with `file` plus either explicit `format` or a `regex` key (then format defaults to `regex`); `trigger.changed` required when `trigger` is present (non-empty list), `ignore_json_paths` default `[]`; `breaking` defaults to `"major"` and must be `major` or `minor`; `tag` optional string that must contain `{version}` or all of `{major}`,`{minor}`,`{patch}`; `after`/`verify` default `[]`, lists of non-empty strings. Unknown keys anywhere are errors (typos must not silently disable a feature). Every error message names the stream and key.

- [ ] **Step 1: Write the failing tests**

`tests/test_config.py`:

```python
from pathlib import Path

import pytest

from version_bump.config import Config, load_config, parse_config
from version_bump.errors import ConfigError

TMI = r'''
[merge]
skip_paths = ["docs/**", "PROGRESS.md", "**/*.md"]

[[stream]]
name = "server"
source = { file = ".version", format = "json-semver" }
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
'''

MINIMAL = '''
[[stream]]
name = "bot"
source = { file = "pyproject.toml", format = "toml-path", path = "project.version" }
'''


def test_parse_full_example():
    cfg = parse_config(TMI)
    assert cfg.skip_paths == ("docs/**", "PROGRESS.md", "**/*.md")
    server, schema = cfg.streams
    assert server.name == "server"
    assert server.source.format == "json-semver"
    assert [t.format for t in server.targets] == ["regex"] * 3
    assert server.breaking == "minor"
    assert server.tag == "v{version}"
    assert server.trigger is None
    assert schema.trigger.changed == ("api-schema/tmi-openapi.json",)
    assert schema.trigger.ignore_json_paths == ("info.version",)
    assert schema.after == ("make generate-api",)
    assert schema.verify == ("scripts/check-embedded-spec.sh",)
    assert cfg.stream("schema") is schema


def test_parse_minimal_defaults():
    cfg = parse_config(MINIMAL)
    assert cfg.skip_paths == ()
    s = cfg.streams[0]
    assert s.breaking == "major"
    assert s.targets == () and s.after == () and s.verify == () and s.tag is None


@pytest.mark.parametrize(
    "text,msg",
    [
        ("", "at least one"),
        ("[[stream]]\nsource = { file = 'x', format = 'json-semver' }\n", "stream\\[0\\].name"),
        (MINIMAL + MINIMAL, "duplicate stream name 'bot'"),
        (MINIMAL.replace('name = "bot"', 'name = "a b"'), "stream\\[0\\].name"),
        (MINIMAL + 'breaking = "patch"\n', "stream 'bot': breaking"),
        (MINIMAL + 'tag = "release"\n', "stream 'bot': tag"),
        (MINIMAL + 'trigger = { ignore_json_paths = ["x"] }\n', "trigger.changed"),
        (MINIMAL + 'trigger = { changed = [] }\n', "trigger.changed"),
        (MINIMAL + "after = [1]\n", "stream 'bot': after"),
        (MINIMAL + 'bogus = 1\n', "unknown key 'bogus'"),
        ("[merge]\nskip = []\n" + MINIMAL, "unknown key 'skip'"),
        (MINIMAL + 'targets = [{ file = "x" }]\n', "targets\\[0\\]"),
        (MINIMAL.replace("toml-path", "nope"), "unknown format"),
        ("not = [toml\n", "invalid TOML"),
    ],
)
def test_parse_errors(text, msg):
    with pytest.raises(ConfigError, match=msg):
        parse_config(text)


def test_load_config_missing(tmp_path: Path):
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / ".github" / "version-bump.toml")


def test_load_config_reads_file(tmp_path: Path):
    p = tmp_path / "version-bump.toml"
    p.write_text(MINIMAL)
    assert isinstance(load_config(p), Config)


def test_unknown_stream_name():
    with pytest.raises(ConfigError, match="no stream named 'x'"):
        parse_config(MINIMAL).stream("x")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_config.py`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement config.py**

```python
"""Load and validate .github/version-bump.toml (spec: Config)."""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from version_bump.errors import ConfigError
from version_bump.formats import FileSpec, validate_spec
from version_bump.pathglob import compile_glob
from version_bump.semver import Level

DEFAULT_CONFIG_PATH = ".github/version-bump.toml"
_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")
_STREAM_KEYS = {"name", "source", "targets", "trigger", "breaking", "tag", "after", "verify"}
_SPEC_KEYS = {"file", "format", "path", "regex"}


@dataclass(frozen=True)
class Trigger:
    changed: tuple[str, ...]
    ignore_json_paths: tuple[str, ...]


@dataclass(frozen=True)
class Stream:
    name: str
    source: FileSpec
    targets: tuple[FileSpec, ...]
    trigger: Trigger | None
    breaking: Level
    tag: str | None
    after: tuple[str, ...]
    verify: tuple[str, ...]


@dataclass(frozen=True)
class Config:
    skip_paths: tuple[str, ...]
    streams: tuple[Stream, ...]

    def stream(self, name: str) -> Stream:
        for s in self.streams:
            if s.name == name:
                return s
        raise ConfigError(f"no stream named {name!r}")


def _reject_unknown(table: dict[str, Any], allowed: set[str], where: str) -> None:
    for k in table:
        if k not in allowed:
            raise ConfigError(f"{where}: unknown key {k!r} (allowed: {', '.join(sorted(allowed))})")


def _str_list(value: Any, where: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(x, str) and x for x in value):
        raise ConfigError(f"{where}: must be a list of non-empty strings")
    return tuple(value)


def _file_spec(table: Any, where: str, role: str) -> FileSpec:
    if not isinstance(table, dict):
        raise ConfigError(f"{where}: must be a table with 'file' and 'format'")
    _reject_unknown(table, _SPEC_KEYS, where)
    file = table.get("file")
    if not isinstance(file, str) or not file:
        raise ConfigError(f"{where}: 'file' is required")
    fmt = table.get("format")
    if fmt is None and "regex" in table:
        fmt = "regex"
    if not isinstance(fmt, str):
        raise ConfigError(f"{where}: 'format' is required (or give 'regex' for the regex format)")
    spec = FileSpec(file=file, format=fmt, path=table.get("path"), regex=table.get("regex"))
    try:
        validate_spec(spec, role)
    except ConfigError as exc:
        raise ConfigError(f"{where}: {exc}") from None
    return spec


def _trigger(table: Any, where: str) -> Trigger:
    if not isinstance(table, dict):
        raise ConfigError(f"{where}: trigger must be a table")
    _reject_unknown(table, {"changed", "ignore_json_paths"}, f"{where}.trigger")
    changed = _str_list(table.get("changed", []), f"{where}.trigger.changed")
    if not changed:
        raise ConfigError(f"{where}.trigger.changed: must list at least one path pattern")
    for p in changed:
        compile_glob(p)
    return Trigger(changed, _str_list(table.get("ignore_json_paths", []), f"{where}.trigger.ignore_json_paths"))


def _stream(table: Any, index: int) -> Stream:
    where = f"stream[{index}]"
    if not isinstance(table, dict):
        raise ConfigError(f"{where}: must be a table")
    name = table.get("name")
    if not isinstance(name, str) or not _NAME_RE.match(name):
        raise ConfigError(f"{where}.name: required, letters/digits/._- only")
    where = f"stream {name!r}"
    _reject_unknown(table, _STREAM_KEYS, where)
    source = _file_spec(table.get("source"), f"{where}: source", "source")
    raw_targets = table.get("targets", [])
    if not isinstance(raw_targets, list):
        raise ConfigError(f"{where}: targets must be a list of tables")
    targets = tuple(_file_spec(t, f"{where}: targets[{i}]", "target") for i, t in enumerate(raw_targets))
    trigger = _trigger(table["trigger"], where) if "trigger" in table else None
    breaking = table.get("breaking", "major")
    if breaking not in ("major", "minor"):
        raise ConfigError(f"{where}: breaking must be 'major' or 'minor', got {breaking!r}")
    tag = table.get("tag")
    if tag is not None:
        ok = isinstance(tag, str) and (
            "{version}" in tag or all(f"{{{c}}}" in tag for c in ("major", "minor", "patch"))
        )
        if not ok:
            raise ConfigError(f"{where}: tag must contain {{version}} (or {{major}}.{{minor}}.{{patch}})")
    return Stream(
        name=name,
        source=source,
        targets=targets,
        trigger=trigger,
        breaking=breaking,
        tag=tag,
        after=_str_list(table.get("after", []), f"{where}: after"),
        verify=_str_list(table.get("verify", []), f"{where}: verify"),
    )


def parse_config(text: str, where: str = "config") -> Config:
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{where}: invalid TOML: {exc}") from None
    _reject_unknown(data, {"merge", "stream"}, where)
    merge = data.get("merge", {})
    if not isinstance(merge, dict):
        raise ConfigError(f"{where}: [merge] must be a table")
    _reject_unknown(merge, {"skip_paths"}, f"{where}: [merge]")
    skip_paths = _str_list(merge.get("skip_paths", []), f"{where}: merge.skip_paths")
    for p in skip_paths:
        compile_glob(p)
    raw_streams = data.get("stream", [])
    if not isinstance(raw_streams, list) or not raw_streams:
        raise ConfigError(f"{where}: at least one [[stream]] is required")
    streams = tuple(_stream(s, i) for i, s in enumerate(raw_streams))
    seen: set[str] = set()
    for s in streams:
        if s.name in seen:
            raise ConfigError(f"{where}: duplicate stream name {s.name!r}")
        seen.add(s.name)
    return Config(skip_paths=skip_paths, streams=streams)


def load_config(path: Path) -> Config:
    if not path.is_file():
        raise ConfigError(f"config file not found: {path}")
    return parse_config(path.read_text(encoding="utf-8"), where=str(path))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_config.py && uv run ruff check . && uv run ruff format --check .`
Expected: all passed.

- [ ] **Step 5: Commit**

```bash
git add src/version_bump/config.py tests/test_config.py
git commit -m "feat(config): load and validate version-bump.toml"
```

---

### Task 7: Git helpers and the scratch-repo test fixture

**Files:**
- Create: `src/version_bump/gitops.py`
- Create: `tests/conftest.py`
- Test: `tests/test_gitops.py`

**Interfaces:**
- Produces (`gitops.py`): `git(repo: Path, *args: str, check: bool = True) -> str` (stripped stdout; `GitError` on failure when `check`), `rev_parse(repo, ref) -> str`, `parent(repo, sha) -> str | None`, `show_file(repo, ref, path) -> str | None` (None when the path does not exist at ref), `changed_paths(repo, sha) -> list[str]` (vs first parent; vs empty tree for a root commit), `first_parent_range(repo, base, ref) -> list[str]` (oldest first, excluding base), `commits_touching(repo, ref, paths: Sequence[str]) -> list[str]` (first-parent, newest first), `subject(repo, sha) -> str`, `tag_target(repo, tag) -> str | None` (peeled commit sha), `create_tag(repo, tag, sha) -> None`, `head_tree_clean(repo) -> bool`.
- Produces (`conftest.py`): fixture `repo(tmp_path) -> ScratchRepo` with `.path: Path`, `.write(relpath, text)`, `.commit(subject: str, body: str = "") -> str` (adds everything, returns sha), `.git(*args) -> str`, `.merge_branch(name, subject) -> str` (creates a non-fast-forward merge commit, used by the Review Focus merge-commit test).

All subprocesses: `stdin=subprocess.DEVNULL`, `text=True`, `encoding="utf-8"`, `errors="surrogateescape"`, env with `GIT_CONFIG_GLOBAL=/dev/null`, `GIT_CONFIG_NOSYSTEM=1`, `LC_ALL=C.UTF-8`. The fixture additionally sets `GIT_AUTHOR_DATE`/`GIT_COMMITTER_DATE` to `2026-01-01T00:00:00Z` and never adds a remote.

- [ ] **Step 1: Write the fixture**

`tests/conftest.py`:

```python
"""Scratch git repos for tests. Local only: never a remote, never a push, never gh."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

FIXED_ENV = {
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "Test Author",
    "GIT_AUTHOR_EMAIL": "test@example.invalid",
    "GIT_COMMITTER_NAME": "Test Author",
    "GIT_COMMITTER_EMAIL": "test@example.invalid",
    "GIT_AUTHOR_DATE": "2026-01-01T00:00:00Z",
    "GIT_COMMITTER_DATE": "2026-01-01T00:00:00Z",
    "LC_ALL": "C.UTF-8",
}


def run_git(path: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=path,
        env={**os.environ, **FIXED_ENV},
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=True,
    )
    return proc.stdout.strip()


@dataclass
class ScratchRepo:
    path: Path

    def git(self, *args: str) -> str:
        return run_git(self.path, *args)

    def write(self, relpath: str, text: str) -> None:
        p = self.path / relpath
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8", newline="")

    def commit(self, subject: str, body: str = "") -> str:
        self.git("add", "-A")
        args = ["commit", "--allow-empty", "-q", "-m", subject]
        if body:
            args += ["-m", body]
        self.git(*args)
        return self.git("rev-parse", "HEAD")

    def merge_branch(self, name: str, subject: str) -> str:
        """Create a true merge commit of branch `name` into the current branch."""
        self.git("merge", "--no-ff", "--no-edit", "-m", subject, name)
        return self.git("rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ScratchRepo:
    for k, v in FIXED_ENV.items():
        monkeypatch.setenv(k, v)
    path = tmp_path / "repo"
    path.mkdir()
    run_git(path, "init", "-q", "-b", "main")
    run_git(path, "config", "commit.gpgsign", "false")
    run_git(path, "config", "tag.gpgsign", "false")
    run_git(path, "config", "user.name", "Test Author")
    run_git(path, "config", "user.email", "test@example.invalid")
    return ScratchRepo(path)
```

- [ ] **Step 2: Write the failing tests**

`tests/test_gitops.py`:

```python
import pytest

from version_bump import gitops
from version_bump.errors import GitError


def test_show_file_and_missing(repo):
    repo.write("a.txt", "one\n")
    sha = repo.commit("chore: init")
    assert gitops.show_file(repo.path, sha, "a.txt") == "one\n"
    assert gitops.show_file(repo.path, sha, "nope.txt") is None
    assert gitops.show_file(repo.path, "HEAD", "a.txt") == "one\n"


def test_parent_and_changed_paths(repo):
    repo.write("a.txt", "one\n")
    root = repo.commit("chore: init")
    repo.write("b/c.txt", "two\n")
    repo.write("a.txt", "three\n")
    second = repo.commit("fix: two files")
    assert gitops.parent(repo.path, root) is None
    assert gitops.parent(repo.path, second) == root
    assert gitops.changed_paths(repo.path, root) == ["a.txt"]
    assert gitops.changed_paths(repo.path, second) == ["a.txt", "b/c.txt"]


def test_first_parent_range_and_subjects(repo):
    repo.write("a", "0")
    base = repo.commit("chore: base")
    repo.write("a", "1")
    c1 = repo.commit("fix: one")
    repo.write("a", "2")
    c2 = repo.commit("feat: two")
    assert gitops.first_parent_range(repo.path, base, "HEAD") == [c1, c2]
    assert gitops.first_parent_range(repo.path, c2, "HEAD") == []
    assert gitops.subject(repo.path, c2) == "feat: two"


def test_first_parent_range_skips_second_parent_commits(repo):
    repo.write("a", "0")
    base = repo.commit("chore: base")
    repo.git("checkout", "-q", "-b", "topic")
    repo.write("b", "1")
    repo.commit("fix: on topic")
    repo.git("checkout", "-q", "main")
    repo.write("a", "1")
    on_main = repo.commit("fix: on main")
    merge = repo.merge_branch("topic", "Merge branch 'topic'")
    assert gitops.first_parent_range(repo.path, base, "HEAD") == [on_main, merge]
    assert gitops.changed_paths(repo.path, merge) == ["b"]


def test_commits_touching(repo):
    repo.write(".version", "1")
    c1 = repo.commit("chore: v")
    repo.write("other", "x")
    repo.commit("fix: other")
    repo.write(".version", "2")
    c3 = repo.commit("chore: v2")
    assert gitops.commits_touching(repo.path, "HEAD", [".version"]) == [c3, c1]
    assert gitops.commits_touching(repo.path, "HEAD", ["missing"]) == []


def test_tags(repo):
    repo.write("a", "0")
    sha = repo.commit("chore: base")
    assert gitops.tag_target(repo.path, "v1.0.0") is None
    gitops.create_tag(repo.path, "v1.0.0", sha)
    assert gitops.tag_target(repo.path, "v1.0.0") == sha


def test_git_error(repo):
    with pytest.raises(GitError, match="rev-parse"):
        gitops.rev_parse(repo.path, "does-not-exist")


def test_head_tree_clean(repo):
    repo.write("a", "0")
    repo.commit("chore: base")
    assert gitops.head_tree_clean(repo.path)
    repo.write("a", "1")
    assert not gitops.head_tree_clean(repo.path)
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/test_gitops.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'version_bump.gitops'`.

- [ ] **Step 4: Implement gitops.py**

```python
"""Thin git wrappers. Every call: stdin=DEVNULL, no global/system config, UTF-8."""

from __future__ import annotations

import os
import subprocess
from collections.abc import Sequence
from pathlib import Path

from version_bump.errors import GitError

_ENV_OVERRIDES = {"GIT_CONFIG_NOSYSTEM": "1", "LC_ALL": "C.UTF-8"}
EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"


def git(repo: Path, *args: str, check: bool = True) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=repo,
        env={**os.environ, **_ENV_OVERRIDES},
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="surrogateescape",
        check=False,
    )
    if check and proc.returncode != 0:
        raise GitError(f"git {' '.join(args)} failed ({proc.returncode}): {proc.stderr.strip()}")
    return proc.stdout.strip()


def rev_parse(repo: Path, ref: str) -> str:
    return git(repo, "rev-parse", "--verify", f"{ref}^{{commit}}")


def parent(repo: Path, sha: str) -> str | None:
    out = git(repo, "rev-parse", "--verify", "-q", f"{sha}^1", check=False)
    return out or None


def show_file(repo: Path, ref: str, path: str) -> str | None:
    proc = subprocess.run(
        ["git", "show", f"{ref}:{path}"],
        cwd=repo,
        env={**os.environ, **_ENV_OVERRIDES},
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="surrogateescape",
        check=False,
    )
    if proc.returncode != 0:
        return None
    return proc.stdout  # NOT stripped: file bytes matter


def changed_paths(repo: Path, sha: str) -> list[str]:
    """Paths changed by sha relative to its first parent (or to the empty tree for a root)."""
    base = parent(repo, sha) or EMPTY_TREE
    out = git(repo, "diff", "--name-only", "--no-renames", base, sha)
    return sorted(line for line in out.splitlines() if line)


def first_parent_range(repo: Path, base: str, ref: str) -> list[str]:
    out = git(repo, "rev-list", "--first-parent", "--reverse", f"{base}..{ref}")
    return [line for line in out.splitlines() if line]


def commits_touching(repo: Path, ref: str, paths: Sequence[str]) -> list[str]:
    if not paths:
        return []
    out = git(repo, "log", "--first-parent", "--format=%H", ref, "--", *paths)
    return [line for line in out.splitlines() if line]


def subject(repo: Path, sha: str) -> str:
    return git(repo, "log", "-1", "--format=%s", sha)


def tag_target(repo: Path, tag: str) -> str | None:
    out = git(repo, "rev-parse", "--verify", "-q", f"refs/tags/{tag}^{{commit}}", check=False)
    return out or None


def create_tag(repo: Path, tag: str, sha: str) -> None:
    git(repo, "tag", tag, sha)


def head_tree_clean(repo: Path) -> bool:
    return git(repo, "status", "--porcelain", "--untracked-files=no") == ""
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_gitops.py && uv run ruff check . && uv run ruff format --check .`
Expected: all passed.

- [ ] **Step 6: Commit**

```bash
git add src/version_bump/gitops.py tests/conftest.py tests/test_gitops.py
git commit -m "feat(gitops): add git helpers and local scratch-repo test fixture"
```

---

### Task 8: `plan`: fold base, triggers, bump fold, JSON output, CLI

**Files:**
- Create: `src/version_bump/plan.py`
- Modify: `src/version_bump/cli.py` (add the `plan` subcommand)
- Test: `tests/test_plan.py`, extend `tests/test_cli.py`

**Interfaces:**
- Consumes: `Config`, `Stream`, `load_config` (Task 6); `read_full`, `read_partial` (Task 5); `Version`, `bump_level` (Task 2); `all_match`, `matches_any` (Task 3); `delete_json_paths` (Task 4); `gitops` (Task 7).
- Produces:
  - `PendingCommit(commit: str, subject: str, streams: list[str])`, `StreamPlan(name, from_version: str, to_version: str, tag: str | None, after: list[str], files: list[str])`, `Plan(ref, base, pending, streams, commit_subject, commit_body)` with `to_dict()`, `to_json() -> str`, `Plan.from_dict(d)`, `Plan.from_json(text)`. JSON keys: `ref`, `base`, `pending[].{commit,subject,streams}`, `streams[].{name,from,to,tag,after,files}`, `commit_subject`, `commit_body` (the shared contract at the top of this plan).
  - `source_value(repo, stream, ref) -> Version | None` (None when the file is absent at ref or unparsable at a historical ref), `find_base(repo, config, ref) -> str`, `is_triggered(repo, stream, sha, changed) -> bool`, `render_tag(template, v: Version) -> str`, `compute_plan(repo: Path, config: Config, ref: str = "HEAD", worktree: bool = False) -> Plan`.
  - CLI: `version-bump plan [--ref REF] [--worktree]` prints `Plan.to_json()` to stdout, exit 0 (also when nothing is pending).

Semantics:
- **Fold base:** candidates = `commits_touching(ref, all source files)` (newest first). For each, compare every stream's `source_value` at the commit vs at its first parent (absent/unparsable counts as a distinct value). The first commit where any stream's value differs is the base. If none, `ConfigError("no commit on <ref> ever set a source value; commit the version files first")`.
- **Current values** = `source_value(ref)` for each stream; a missing/unparsable source at `ref` is a `ConfigError` naming the stream and file (Review Focus 2).
- **Pending** = `first_parent_range(base, ref)`; a commit whose `changed_paths` all match `skip_paths` is dropped (not listed). The remaining are listed in `pending` oldest first.
- **Trigger:** a stream without `trigger` bumps for every pending commit. With one, it bumps only when some changed path matches `trigger.changed` AND, for a matching path ending in `.json` when `ignore_json_paths` is non-empty, the JSON at `sha^1` and `sha` differ after `delete_json_paths` (parse failure on either side -> treat as changed; absent on one side -> changed). Non-JSON matches always count.
- **Fold:** for each stream, `to = from`; for each pending commit that bumps it, `to = to.bump(bump_level(subject, stream.breaking))`. A stream bumps iff at least one commit bumped it (then `to != from` is guaranteed).
- **Worktree mode** (`--worktree`, workflow step 6): read each stream's current value from the working tree file instead of `ref`. If any stream's worktree value differs from its value at `ref`, the working tree is the virtual bump commit: `base = "WORKTREE"`, `pending = []`, `streams = []`. Otherwise fall through to the normal computation. In either case, first check that every target's `read_partial` matches the source in the working tree and raise `GuardError` listing mismatches (this is the "self-consistent commit" proof).
- **Commit message:** subject `chore(version): bump <name> to X.Y.Z[, <name> to A.B.C]` over bumped streams in config order; body `Folds N merged commit(s):` then `- <sha[:7]> <subject>` per pending commit. Both empty strings when no stream bumps.
- `render_tag`: `template.format(version=str(v), major=v.major, minor=v.minor, patch=v.patch)`.

- [ ] **Step 1: Write the failing tests**

`tests/test_plan.py`:

```python
import json

import pytest

from version_bump.config import parse_config
from version_bump.errors import ConfigError, GuardError
from version_bump.plan import Plan, compute_plan, find_base, render_tag
from version_bump.semver import Version

CONFIG = r'''
[merge]
skip_paths = ["docs/**", "PROGRESS.md", "**/*.md"]

[[stream]]
name = "server"
source = { file = ".version", format = "json-semver" }
targets = [{ file = "api/version.go", regex = 'Version = "(?P<version>\d+\.\d+\.\d+)"' }]
breaking = "minor"
tag = "v{version}"

[[stream]]
name = "schema"
source = { file = "api-schema/openapi.json", format = "json-path", path = "info.version" }
trigger = { changed = ["api-schema/openapi.json"], ignore_json_paths = ["info.version"] }
breaking = "major"
after = ["make generate-api"]
'''


def seed(repo, server="1.8.16", schema="2.3.1", spec_paths='{"/a": {}}'):
    ma, mi, pa = server.split(".")
    repo.write(".version", f'{{"major": {ma}, "minor": {mi}, "patch": {pa}, "prerelease": ""}}\n')
    repo.write("api/version.go", f'package api\n\nconst Version = "{server}"\n')
    repo.write("api-schema/openapi.json", f'{{"info": {{"version": "{schema}"}}, "paths": {spec_paths}}}\n')
    repo.write("main.go", "package main\n")
    return repo.commit(f"chore(version): bump server to {server}")


@pytest.fixture
def cfg():
    return parse_config(CONFIG)


def plan_of(repo, cfg, **kw) -> Plan:
    return compute_plan(repo.path, cfg, **kw)


def test_right_after_bump_nothing_pending(repo, cfg):
    base = seed(repo)
    p = plan_of(repo, cfg)
    assert p.base == base and p.pending == [] and p.streams == []
    assert p.commit_subject == "" and p.commit_body == ""


def test_docs_only_commit_is_skipped(repo, cfg):
    seed(repo)
    repo.write("docs/a.md", "x")
    repo.write("README.md", "y")
    repo.commit("docs: notes (#1)")
    p = plan_of(repo, cfg)
    assert p.pending == [] and p.streams == []


def test_fold_fix_feat_schema_fix(repo, cfg):
    seed(repo)
    repo.write("main.go", "package main // one\n")
    c1 = repo.commit("fix: one (#2)")
    repo.write("api-schema/openapi.json", '{"info": {"version": "2.3.1"}, "paths": {"/a": {}, "/b": {}}}\n')
    c2 = repo.commit("feat(api): add b (#3)")
    repo.write("main.go", "package main // two\n")
    c3 = repo.commit("fix: two (#4)")
    p = plan_of(repo, cfg)
    assert [c.commit for c in p.pending] == [c1, c2, c3]
    assert [c.streams for c in p.pending] == [["server"], ["server", "schema"], ["server"]]
    server, schema = p.streams
    assert (server.from_version, server.to_version, server.tag) == ("1.8.16", "1.9.1", "v1.9.1")
    assert (schema.from_version, schema.to_version, schema.tag) == ("2.3.1", "2.4.0", None)
    assert schema.after == ["make generate-api"]
    assert server.files == [".version", "api/version.go"]  # deduplicated, source first
    assert p.commit_subject == "chore(version): bump server to 1.9.1, schema to 2.4.0"
    assert p.commit_body.startswith("Folds 3 merged commit(s):\n- " + c1[:7] + " fix: one (#2)\n")


def test_no_cascade_after_bump_commit(repo, cfg):
    seed(repo)
    repo.write("main.go", "package main // one\n")
    repo.commit("fix: one (#2)")
    bump = seed(repo, server="1.8.17")  # the bot's own commit: changes the source value
    p = plan_of(repo, cfg)
    assert p.base == bump and p.pending == [] and p.streams == []


def test_find_base_ignores_touch_without_value_change(repo, cfg):
    base = seed(repo)
    # Reformat .version without changing its value: must NOT become the base.
    repo.write(".version", '{"major":1,"minor":8,"patch":16,"prerelease":"rc1"}\n')
    touch = repo.commit("style: reformat version file")
    assert find_base(repo.path, cfg, "HEAD") == base
    p = plan_of(repo, cfg)
    assert [c.commit for c in p.pending] == [touch]
    assert [s.to_version for s in p.streams] == ["1.8.17"]


def test_breaking_levels(repo, cfg):
    seed(repo)
    repo.write("api-schema/openapi.json", '{"info": {"version": "2.3.1"}, "paths": {}}\n')
    repo.commit("feat(api)!: breaking rewrite")
    p = plan_of(repo, cfg)
    assert {s.name: s.to_version for s in p.streams} == {"server": "1.9.0", "schema": "3.0.0"}


def test_untriggered_stream_does_not_bump(repo, cfg):
    seed(repo)
    repo.write("main.go", "package main // x\n")
    repo.commit("feat: server only")
    p = plan_of(repo, cfg)
    assert [s.name for s in p.streams] == ["server"]


def test_only_ignored_json_path_change_does_not_trigger(repo, cfg):
    seed(repo)
    repo.write("api-schema/openapi.json", '{"info": {"version": "9.9.9"}, "paths": {"/a": {}}}\n')
    repo.commit("fix: hand-edited version only")
    p = plan_of(repo, cfg)
    assert [s.name for s in p.streams] == ["server"]  # schema not triggered


def test_several_pending_commits_touching_triggered_stream(repo, cfg):
    seed(repo)
    for i in range(3):
        repo.write("api-schema/openapi.json", f'{{"info": {{"version": "2.3.1"}}, "paths": {{"/p{i}": {{}}}}}}\n')
        repo.commit(f"feat: endpoint {i}")
    p = plan_of(repo, cfg)
    assert {s.name: s.to_version for s in p.streams} == {"server": "1.11.0", "schema": "2.6.0"}


def test_plan_merge_commit_uses_first_parent_diff(repo, cfg):
    seed(repo)
    repo.git("checkout", "-q", "-b", "topic")
    repo.write("api-schema/openapi.json", '{"info": {"version": "2.3.1"}, "paths": {"/z": {}}}\n')
    repo.commit("feat: on topic")
    repo.git("checkout", "-q", "main")
    repo.write("main.go", "package main // main\n")
    repo.commit("fix: on main")
    merge = repo.merge_branch("topic", "Merge pull request #5 from x/topic")
    p = plan_of(repo, cfg)
    assert p.pending[-1].commit == merge
    assert p.pending[-1].streams == ["server", "schema"]  # first-parent diff shows the spec change
    assert {s.name: s.to_version for s in p.streams} == {"server": "1.8.18", "schema": "2.3.2"}


def test_plan_subject_with_shell_metacharacters_round_trips(repo, cfg):
    seed(repo)
    subject = "fix: `rm -rf` $(echo hi) \"quoted\" 'single' (#7)"
    repo.write("main.go", "package main // s\n")
    repo.commit(subject)
    p = plan_of(repo, cfg)
    assert p.pending[0].subject == subject
    again = Plan.from_json(p.to_json())
    assert again.pending[0].subject == subject and again.commit_body == p.commit_body


def test_plan_missing_source_at_head_is_config_error(repo, cfg):
    seed(repo)
    repo.git("rm", "-q", "api-schema/openapi.json")
    repo.commit("fix: drop spec")
    with pytest.raises(ConfigError, match="stream 'schema'.*api-schema/openapi.json"):
        plan_of(repo, cfg)


def test_no_base_is_config_error(repo, cfg):
    repo.write("main.go", "package main\n")
    repo.commit("chore: no version files yet")
    with pytest.raises(ConfigError, match="never set a source value"):
        find_base(repo.path, cfg, "HEAD")


def test_worktree_mode_sees_virtual_bump_commit(repo, cfg):
    seed(repo)
    repo.write("main.go", "package main // one\n")
    repo.commit("fix: one (#2)")
    assert plan_of(repo, cfg).streams != []
    # Simulate apply: write the new values into the working tree (source + target).
    repo.write(".version", '{"major": 1, "minor": 8, "patch": 17, "prerelease": ""}\n')
    repo.write("api/version.go", 'package api\n\nconst Version = "1.8.17"\n')
    p = plan_of(repo, cfg, worktree=True)
    assert p.base == "WORKTREE" and p.pending == [] and p.streams == []


def test_worktree_mode_fails_when_target_disagrees(repo, cfg):
    seed(repo)
    repo.write(".version", '{"major": 1, "minor": 8, "patch": 17, "prerelease": ""}\n')
    with pytest.raises(GuardError, match="api/version.go"):
        plan_of(repo, cfg, worktree=True)


def test_worktree_mode_without_changes_equals_normal_plan(repo, cfg):
    seed(repo)
    repo.write("main.go", "package main // one\n")
    repo.commit("fix: one (#2)")
    assert plan_of(repo, cfg, worktree=True).to_dict() == plan_of(repo, cfg).to_dict()


def test_render_tag():
    assert render_tag("v{version}", Version(1, 2, 3)) == "v1.2.3"
    assert render_tag("rel-{major}.{minor}", Version(1, 2, 3)) == "rel-1.2"


def test_plan_json_shape(repo, cfg):
    seed(repo)
    repo.write("main.go", "package main // one\n")
    repo.commit("fix: one (#2)")
    d = json.loads(plan_of(repo, cfg).to_json())
    assert set(d) == {"ref", "base", "pending", "streams", "commit_subject", "commit_body"}
    assert set(d["pending"][0]) == {"commit", "subject", "streams"}
    assert set(d["streams"][0]) == {"name", "from", "to", "tag", "after", "files"}
```

Append to `tests/test_cli.py`:

```python
def test_cli_plan_prints_json(repo, capsys):
    repo.write(".github/version-bump.toml", MINIMAL_CFG)
    repo.write("pyproject.toml", '[project]\nname = "x"\nversion = "0.1.0"\n')
    repo.commit("chore: init")
    repo.write("src.py", "x = 1\n")
    repo.commit("feat: thing")
    assert main(["--repo", str(repo.path), "plan"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["streams"][0]["to"] == "0.2.0"


def test_cli_error_prints_one_line_and_exits_1(repo, capsys):
    assert main(["--repo", str(repo.path), "plan"]) == 1
    err = capsys.readouterr().err
    assert err.startswith("error: config file not found") and err.count("\n") == 1
```

and at the top of `tests/test_cli.py` add:

```python
import json

MINIMAL_CFG = '''
[[stream]]
name = "bot"
source = { file = "pyproject.toml", format = "toml-path", path = "project.version" }
tag = "v{version}"
'''
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_plan.py tests/test_cli.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'version_bump.plan'` and, for the CLI tests, `argparse` errors about the unknown `plan` command.

- [ ] **Step 3: Implement plan.py**

```python
"""The fold: which commits are pending, which streams they bump, and to what (spec: Bump rules)."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from version_bump import gitops
from version_bump.config import Config, Stream
from version_bump.errors import ConfigError, GuardError, VersionBumpError
from version_bump.formats import read_full, read_partial
from version_bump.jsonpos import delete_json_paths
from version_bump.pathglob import all_match, matches_any
from version_bump.semver import Version, bump_level

WORKTREE = "WORKTREE"


@dataclass
class PendingCommit:
    commit: str
    subject: str
    streams: list[str] = field(default_factory=list)


@dataclass
class StreamPlan:
    name: str
    from_version: str
    to_version: str
    tag: str | None
    after: list[str]
    files: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "from": self.from_version,
            "to": self.to_version,
            "tag": self.tag,
            "after": list(self.after),
            "files": list(self.files),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> StreamPlan:
        return cls(d["name"], d["from"], d["to"], d.get("tag"), list(d["after"]), list(d["files"]))


@dataclass
class Plan:
    ref: str
    base: str
    pending: list[PendingCommit]
    streams: list[StreamPlan]
    commit_subject: str
    commit_body: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "ref": self.ref,
            "base": self.base,
            "pending": [asdict(c) for c in self.pending],
            "streams": [s.to_dict() for s in self.streams],
            "commit_subject": self.commit_subject,
            "commit_body": self.commit_body,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False) + "\n"

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Plan:
        return cls(
            ref=d["ref"],
            base=d["base"],
            pending=[PendingCommit(c["commit"], c["subject"], list(c["streams"])) for c in d["pending"]],
            streams=[StreamPlan.from_dict(s) for s in d["streams"]],
            commit_subject=d["commit_subject"],
            commit_body=d["commit_body"],
        )

    @classmethod
    def from_json(cls, text: str) -> Plan:
        try:
            return cls.from_dict(json.loads(text))
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise VersionBumpError(f"invalid plan JSON: {exc}") from None


def render_tag(template: str, v: Version) -> str:
    return template.format(version=str(v), major=v.major, minor=v.minor, patch=v.patch)


def source_value(repo: Path, stream: Stream, ref: str) -> Version | None:
    """The stream's source value at ref, or None when absent or unreadable there."""
    text = gitops.show_file(repo, ref, stream.source.file)
    if text is None:
        return None
    try:
        return read_full(text, stream.source)
    except VersionBumpError:
        return None


def _worktree_value(repo: Path, stream: Stream) -> Version:
    p = repo / stream.source.file
    if not p.is_file():
        raise ConfigError(f"stream {stream.name!r}: source file {stream.source.file} not found in the working tree")
    return read_full(p.read_text(encoding="utf-8"), stream.source)


def _current_value(repo: Path, stream: Stream, ref: str) -> Version:
    text = gitops.show_file(repo, ref, stream.source.file)
    if text is None:
        raise ConfigError(f"stream {stream.name!r}: source file {stream.source.file} not found at {ref}")
    try:
        return read_full(text, stream.source)
    except VersionBumpError as exc:
        raise ConfigError(f"stream {stream.name!r}: cannot read {stream.source.file} at {ref}: {exc}") from None


def find_base(repo: Path, config: Config, ref: str) -> str:
    """Newest first-parent commit on ref that changed any stream's source VALUE."""
    files = sorted({s.source.file for s in config.streams})
    for sha in gitops.commits_touching(repo, ref, files):
        prev = gitops.parent(repo, sha)
        for stream in config.streams:
            now = source_value(repo, stream, sha)
            before = source_value(repo, stream, prev) if prev else None
            if now != before:
                return sha
    raise ConfigError(f"no commit on {ref} ever set a source value; commit the version files first")


def _json_differs_ignoring(repo: Path, sha: str, path: str, ignore: tuple[str, ...]) -> bool:
    prev = gitops.parent(repo, sha)
    before = gitops.show_file(repo, prev, path) if prev else None
    after = gitops.show_file(repo, sha, path)
    if before is None or after is None:
        return True
    try:
        a = delete_json_paths(json.loads(before), ignore)
        b = delete_json_paths(json.loads(after), ignore)
    except json.JSONDecodeError:
        return True
    return a != b


def is_triggered(repo: Path, stream: Stream, sha: str, changed: list[str]) -> bool:
    if stream.trigger is None:
        return True
    for path in changed:
        if not matches_any(stream.trigger.changed, path):
            continue
        if stream.trigger.ignore_json_paths and path.endswith(".json"):
            if _json_differs_ignoring(repo, sha, path, stream.trigger.ignore_json_paths):
                return True
            continue
        return True
    return False


def _check_worktree_consistency(repo: Path, config: Config) -> None:
    bad: list[str] = []
    for stream in config.streams:
        src = _worktree_value(repo, stream)
        for t in stream.targets:
            p = repo / t.file
            if not p.is_file():
                bad.append(f"{stream.name}: target {t.file} missing")
                continue
            got = read_partial(p.read_text(encoding="utf-8"), t)
            if not got.matches(src):
                bad.append(f"{stream.name}: target {t.file} has {got.text}, source has {src}")
    if bad:
        raise GuardError("working tree is not self-consistent: " + "; ".join(bad))


def _message(streams: list[StreamPlan], pending: list[PendingCommit]) -> tuple[str, str]:
    if not streams:
        return "", ""
    subject = "chore(version): bump " + ", ".join(f"{s.name} to {s.to_version}" for s in streams)
    body = f"Folds {len(pending)} merged commit(s):\n" + "".join(
        f"- {c.commit[:7]} {c.subject}\n" for c in pending
    )
    return subject, body.rstrip("\n")


def compute_plan(repo: Path, config: Config, ref: str = "HEAD", worktree: bool = False) -> Plan:
    ref_sha = gitops.rev_parse(repo, ref)
    current = {s.name: _current_value(repo, s, ref_sha) for s in config.streams}
    if worktree:
        _check_worktree_consistency(repo, config)
        tree = {s.name: _worktree_value(repo, s) for s in config.streams}
        if any(tree[n] != current[n] for n in current):
            return Plan(ref=ref_sha, base=WORKTREE, pending=[], streams=[], commit_subject="", commit_body="")
    base = find_base(repo, config, ref_sha)
    pending: list[PendingCommit] = []
    to = dict(current)
    bumped: set[str] = set()
    for sha in gitops.first_parent_range(repo, base, ref_sha):
        changed = gitops.changed_paths(repo, sha)
        if all_match(config.skip_paths, changed):
            continue
        subj = gitops.subject(repo, sha)
        entry = PendingCommit(commit=sha, subject=subj)
        for stream in config.streams:
            if is_triggered(repo, stream, sha, changed):
                to[stream.name] = to[stream.name].bump(bump_level(subj, stream.breaking))
                bumped.add(stream.name)
                entry.streams.append(stream.name)
        pending.append(entry)
    streams = [
        StreamPlan(
            name=s.name,
            from_version=str(current[s.name]),
            to_version=str(to[s.name]),
            tag=render_tag(s.tag, to[s.name]) if s.tag else None,
            after=list(s.after),
            files=list(dict.fromkeys([s.source.file] + [t.file for t in s.targets])),
        )
        for s in config.streams
        if s.name in bumped
    ]
    subject, body = _message(streams, pending)
    return Plan(ref=ref_sha, base=base, pending=pending, streams=streams, commit_subject=subject, commit_body=body)
```

- [ ] **Step 4: Add the `plan` subcommand to cli.py**

Replace the `build_parser` function body and add a handler:

```python
from pathlib import Path

from version_bump.config import load_config
from version_bump.plan import compute_plan


def _repo_and_config(args: argparse.Namespace):
    repo = Path(args.repo).resolve()
    return repo, load_config(repo / args.config)


def cmd_plan(args: argparse.Namespace) -> int:
    repo, config = _repo_and_config(args)
    plan = compute_plan(repo, config, ref=args.ref, worktree=args.worktree)
    sys.stdout.write(plan.to_json())
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="version-bump")
    parser.add_argument("--version", action="version", version=f"version-bump {__version__}")
    parser.add_argument("--repo", default=".", help="repository root (default: cwd)")
    parser.add_argument("--config", default=DEFAULT_CONFIG, help="config path relative to --repo")
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    p = sub.add_parser("plan", help="compute the pending bump (read-only); prints JSON")
    p.add_argument("--ref", default="HEAD")
    p.add_argument("--worktree", action="store_true", help="read current values from the working tree")
    p.set_defaults(func=cmd_plan)
    return parser
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest && uv run ruff check . && uv run ruff format --check .`
Expected: all passed.

- [ ] **Step 6: Commit**

```bash
git add src/version_bump/plan.py src/version_bump/cli.py tests/test_plan.py tests/test_cli.py
git commit -m "feat(plan): fold pending commits into per-stream bumps with JSON output"
```

---

### Task 9: `apply` (source of truth + target sync) and `hooks`

**Files:**
- Create: `src/version_bump/apply.py`
- Modify: `src/version_bump/cli.py` (add `apply` and `hooks` subcommands)
- Test: `tests/test_apply.py`

**Interfaces:**
- Consumes: `Plan`, `StreamPlan` (Task 8); `Config` (Task 6); `read_full`, `write_version` (Task 5); `Version` (Task 2); `HookError` (Task 1).
- Produces: `apply_plan(repo: Path, config: Config, plan: Plan) -> list[str]` (repo-relative files written, in order; writes the source first, then every target, each via `write_version`; verifies afterwards that every source reads back as `to`); `run_hooks(repo: Path, plan: Plan) -> list[str]` (runs each bumped stream's `after` commands in config order with `shell=True`, `cwd=repo`, `stdin=DEVNULL`, stdout/stderr inherited; raises `HookError("after hook failed (exit N): <cmd>")` on the first failure; returns the commands run).
- CLI: `version-bump apply --plan FILE` prints one written path per line; `version-bump hooks --plan FILE` prints each command before running it. `--plan -` reads stdin for both.

`apply` refuses (`VersionBumpError`) when `plan.ref` is not the current `HEAD` (the plan is stale) and when any file in `plan.streams[].files` is not present in the working tree. Files are read and written as UTF-8 text with `newline=""` so CRLF survives.

- [ ] **Step 1: Write the failing tests**

`tests/test_apply.py`:

```python
import json

import pytest

from version_bump.apply import apply_plan, run_hooks
from version_bump.config import parse_config
from version_bump.errors import HookError, VersionBumpError
from version_bump.plan import compute_plan

CONFIG = r'''
[[stream]]
name = "server"
source = { file = ".version", format = "json-semver" }
targets = [
  { file = "api/version.go", regex = 'VersionMajor = "(?P<major>\d+)"' },
  { file = "api/version.go", regex = 'VersionMinor = "(?P<minor>\d+)"' },
  { file = "api/version.go", regex = 'VersionPatch = "(?P<patch>\d+)"' },
]
breaking = "minor"
after = ["printf 'gen %s' \"$(cat .version | tr -d '\\n ')\" > generated.txt"]

[[stream]]
name = "lib"
source = { file = "pyproject.toml", format = "toml-path", path = "project.version" }
after = ["false"]
'''

GO = 'package api\n\nconst (\n\tVersionMajor = "1"\n\tVersionMinor = "8"\n\tVersionPatch = "16"\n)\n'


def seed(repo):
    repo.write(".version", '{"major": 1, "minor": 8, "patch": 16, "prerelease": "rc"}\r\n')
    repo.write("api/version.go", GO)
    repo.write("pyproject.toml", '[project]\nname = "x"\nversion = "0.1.0"\n')
    repo.commit("chore(version): seed")


@pytest.fixture
def cfg():
    return parse_config(CONFIG)


def test_apply_writes_source_then_targets_and_preserves_bytes(repo, cfg):
    seed(repo)
    repo.write("main.go", "x\n")
    repo.commit("feat: thing")
    plan = compute_plan(repo.path, cfg)
    written = apply_plan(repo.path, cfg, plan)
    assert written == [".version", "api/version.go", "pyproject.toml"]
    assert (repo.path / ".version").read_bytes() == b'{"major": 1, "minor": 9, "patch": 0, "prerelease": "rc"}\r\n'
    go = (repo.path / "api/version.go").read_text()
    assert 'VersionMajor = "1"' in go and 'VersionMinor = "9"' in go and 'VersionPatch = "0"' in go
    assert 'version = "0.2.0"' in (repo.path / "pyproject.toml").read_text()
    # Re-planning the working tree now sees nothing pending (self-consistent).
    assert compute_plan(repo.path, cfg, worktree=True).streams == []


def test_apply_syncs_targets_even_when_source_already_correct(repo, cfg):
    seed(repo)
    repo.write("main.go", "x\n")
    repo.commit("fix: thing")
    plan = compute_plan(repo.path, cfg)
    # Hand-corrupt a target before apply: apply must rewrite it from the source.
    repo.write("api/version.go", GO.replace('VersionPatch = "16"', 'VersionPatch = "99"'))
    apply_plan(repo.path, cfg, plan)
    assert 'VersionPatch = "17"' in (repo.path / "api/version.go").read_text()


def test_apply_rejects_stale_plan(repo, cfg):
    seed(repo)
    repo.write("main.go", "x\n")
    repo.commit("fix: thing")
    plan = compute_plan(repo.path, cfg)
    repo.write("main.go", "y\n")
    repo.commit("fix: another")
    with pytest.raises(VersionBumpError, match="stale"):
        apply_plan(repo.path, cfg, plan)


def test_apply_rejects_missing_file(repo, cfg):
    seed(repo)
    repo.write("main.go", "x\n")
    repo.commit("fix: thing")
    plan = compute_plan(repo.path, cfg)
    (repo.path / "api/version.go").unlink()
    with pytest.raises(VersionBumpError, match="api/version.go"):
        apply_plan(repo.path, cfg, plan)


def test_run_hooks_runs_only_bumped_streams_and_fails_loudly(repo, cfg):
    seed(repo)
    repo.write("main.go", "x\n")
    repo.commit("fix: thing")
    plan = compute_plan(repo.path, cfg)
    apply_plan(repo.path, cfg, plan)
    with pytest.raises(HookError, match=r"exit 1.*false"):
        run_hooks(repo.path, plan)
    # The first stream's hook ran before the failing one.
    assert (repo.path / "generated.txt").read_text().startswith("gen {")


def test_run_hooks_skips_unbumped_streams(repo, cfg):
    seed(repo)
    only_server = parse_config(CONFIG.replace('after = ["false"]', 'after = ["false"]\ntrigger = { changed = ["pyproject.toml"] }'))
    repo.write("main.go", "x\n")
    repo.commit("fix: thing")
    plan = compute_plan(repo.path, only_server)
    assert [s.name for s in plan.streams] == ["server"]
    apply_plan(repo.path, only_server, plan)
    assert run_hooks(repo.path, plan) == plan.streams[0].after


def test_cli_apply_and_hooks(repo, cfg, capsys):
    from version_bump.cli import main

    repo.write(".github/version-bump.toml", CONFIG.replace('after = ["false"]', ""))
    seed(repo)
    repo.write("main.go", "x\n")
    repo.commit("fix: thing")
    plan_file = repo.path / "plan.json"
    assert main(["--repo", str(repo.path), "plan"]) == 0
    plan_file.write_text(capsys.readouterr().out)
    assert main(["--repo", str(repo.path), "apply", "--plan", str(plan_file)]) == 0
    assert capsys.readouterr().out.splitlines() == [".version", "api/version.go", "pyproject.toml"]
    assert main(["--repo", str(repo.path), "hooks", "--plan", str(plan_file)]) == 0
    assert (repo.path / "generated.txt").exists()
    assert json.loads(plan_file.read_text())["streams"][0]["to"] == "1.8.17"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_apply.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'version_bump.apply'`.

- [ ] **Step 3: Implement apply.py**

```python
"""Write the planned versions (source first, then targets) and run `after` hooks."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from version_bump import gitops
from version_bump.config import Config
from version_bump.errors import HookError, VersionBumpError
from version_bump.formats import FileSpec, read_full, write_version
from version_bump.plan import Plan
from version_bump.semver import Version


def _read(repo: Path, rel: str) -> str:
    p = repo / rel
    if not p.is_file():
        raise VersionBumpError(f"cannot apply: {rel} is not in the working tree")
    with open(p, encoding="utf-8", newline="") as fh:
        return fh.read()


def _write(repo: Path, rel: str, text: str) -> None:
    with open(repo / rel, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)


def _apply_spec(repo: Path, spec: FileSpec, version: Version, written: list[str]) -> None:
    text = _read(repo, spec.file)
    new = write_version(text, spec, version)
    if new != text:
        _write(repo, spec.file, new)
    if spec.file not in written:
        written.append(spec.file)


def apply_plan(repo: Path, config: Config, plan: Plan) -> list[str]:
    head = gitops.rev_parse(repo, "HEAD")
    if plan.ref != head:
        raise VersionBumpError(f"stale plan: computed at {plan.ref[:7]} but HEAD is {head[:7]}; re-run plan")
    written: list[str] = []
    for sp in plan.streams:
        stream = config.stream(sp.name)
        to = Version.parse(sp.to_version)
        _apply_spec(repo, stream.source, to, written)
        for target in stream.targets:
            _apply_spec(repo, target, to, written)
        got = read_full(_read(repo, stream.source.file), stream.source)
        if got != to:
            raise VersionBumpError(f"stream {sp.name!r}: wrote {to} to {stream.source.file} but read back {got}")
    return written


def run_hooks(repo: Path, plan: Plan) -> list[str]:
    ran: list[str] = []
    for sp in plan.streams:
        for cmd in sp.after:
            print(f"+ {cmd}", file=sys.stderr, flush=True)
            proc = subprocess.run(cmd, shell=True, cwd=repo, stdin=subprocess.DEVNULL, check=False)
            if proc.returncode != 0:
                raise HookError(f"stream {sp.name!r}: after hook failed (exit {proc.returncode}): {cmd}")
            ran.append(cmd)
    return ran
```

- [ ] **Step 4: Add the subcommands to cli.py**

Add these handlers and parser entries (inside `build_parser`, after the `plan` parser):

```python
from version_bump.apply import apply_plan, run_hooks
from version_bump.plan import Plan


def _load_plan(path: str) -> Plan:
    text = sys.stdin.read() if path == "-" else Path(path).read_text(encoding="utf-8")
    return Plan.from_json(text)


def cmd_apply(args: argparse.Namespace) -> int:
    repo, config = _repo_and_config(args)
    for rel in apply_plan(repo, config, _load_plan(args.plan)):
        print(rel)
    return 0


def cmd_hooks(args: argparse.Namespace) -> int:
    repo, _ = _repo_and_config(args)
    run_hooks(repo, _load_plan(args.plan))
    return 0


    # in build_parser():
    p = sub.add_parser("apply", help="write source and target files for each bumped stream")
    p.add_argument("--plan", required=True, help="plan JSON file, or - for stdin")
    p.set_defaults(func=cmd_apply)

    p = sub.add_parser("hooks", help="run each bumped stream's `after` commands")
    p.add_argument("--plan", required=True, help="plan JSON file, or - for stdin")
    p.set_defaults(func=cmd_hooks)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest && uv run ruff check . && uv run ruff format --check .`
Expected: all passed.

- [ ] **Step 6: Commit**

```bash
git add src/version_bump/apply.py src/version_bump/cli.py tests/test_apply.py
git commit -m "feat(apply): write source and targets from a plan and run after hooks"
```

---

### Task 10: `guard`: value comparison between base and head, plus verify commands

**Files:**
- Create: `src/version_bump/guard.py`
- Modify: `src/version_bump/cli.py` (add `guard`)
- Test: `tests/test_guard.py`

**Interfaces:**
- Consumes: `Config` (Task 6); `read_full`, `read_partial` (Task 5); `gitops.show_file`, `gitops.rev_parse` (Task 7); `GuardError`, `HookError` (Task 1).
- Produces: `GuardResult(violations: list[str], skipped: list[str])`; `check_values(repo, config, base: str, head: str) -> GuardResult`; `run_verify(repo, config) -> list[str]` (runs every stream's `verify` commands with `shell=True`, `cwd=repo`, `stdin=DEVNULL`; raises `HookError`); `guard(repo, config, base, head) -> GuardResult` (raises `GuardError` listing violations BEFORE running verify; then runs verify).
- CLI: `version-bump guard --base SHA [--head REF]` (head defaults to `HEAD`). Prints `OK: version state untouched (N stream(s) checked)` plus one `note:` line per skipped stream; on violation prints `error: ...` and exits 1.

Rules: for each stream, compare the source value at base vs head (`read_full`); and for each target compare the `read_partial` capture at base vs head. Any difference is a violation `"<stream>: <file> changed <a> -> <b>; only the post-merge bump may write it"`. A stream whose source is absent at base is skipped with `"<stream>: source <file> absent at base (new stream); skipped"` (Review Focus 4). A target absent at base but present at head is also skipped (newly added target). Files that merely contain the version but are not listed (e.g. a generated `api/api.go`) are never examined. Head defaults to `HEAD`.

- [ ] **Step 1: Write the failing tests**

`tests/test_guard.py`:

```python
import pytest

from version_bump.config import parse_config
from version_bump.errors import GuardError, HookError
from version_bump.guard import check_values, guard, run_verify

CONFIG = r'''
[[stream]]
name = "server"
source = { file = ".version", format = "json-semver" }
targets = [{ file = "api/version.go", regex = 'Version = "(?P<version>\d+\.\d+\.\d+)"' }]

[[stream]]
name = "schema"
source = { file = "openapi.json", format = "json-path", path = "info.version" }
verify = ["test \"$(cat generated.txt)\" = \"$(python3 -c 'import json;print(json.load(open(\"openapi.json\"))[\"info\"][\"version\"])')\""]
'''


def seed(repo):
    repo.write(".version", '{"major": 1, "minor": 8, "patch": 16}\n')
    repo.write("api/version.go", 'package api\n\nconst Version = "1.8.16"\n')
    repo.write("openapi.json", '{"info": {"version": "2.3.1"}, "paths": {}}\n')
    repo.write("generated.txt", "2.3.1")
    repo.write("api/api.go", "// generated: 2.3.1\n")
    return repo.commit("chore(version): seed")


@pytest.fixture
def cfg():
    return parse_config(CONFIG)


def test_code_only_pr_passes(repo, cfg):
    base = seed(repo)
    repo.write("main.go", "x\n")
    repo.commit("fix: code only")
    r = check_values(repo.path, cfg, base, "HEAD")
    assert r.violations == [] and r.skipped == []


def test_hand_edited_source_fails(repo, cfg):
    base = seed(repo)
    repo.write(".version", '{"major": 9, "minor": 0, "patch": 0}\n')
    repo.commit("fix: hand bump")
    r = check_values(repo.path, cfg, base, "HEAD")
    assert r.violations == ["server: .version changed 1.8.16 -> 9.0.0; only the post-merge bump may write it"]


def test_hand_edited_target_fails(repo, cfg):
    base = seed(repo)
    repo.write("api/version.go", 'package api\n\nconst Version = "1.8.17"\n')
    repo.commit("fix: hand target bump")
    r = check_values(repo.path, cfg, base, "HEAD")
    assert r.violations == ["server: api/version.go changed 1.8.16 -> 1.8.17; only the post-merge bump may write it"]


def test_hand_edited_json_path_fails(repo, cfg):
    base = seed(repo)
    repo.write("openapi.json", '{"info": {"version": "9.9.9"}, "paths": {}}\n')
    repo.commit("fix: hand schema bump")
    r = check_values(repo.path, cfg, base, "HEAD")
    assert r.violations == ["schema: openapi.json changed 2.3.1 -> 9.9.9; only the post-merge bump may write it"]


def test_regenerated_file_only_passes(repo, cfg):
    base = seed(repo)
    repo.write("api/api.go", "// generated: 2.3.1 (regenerated, different bytes)\n")
    repo.write("openapi.json", '{"info": {"version": "2.3.1"}, "paths": {"/new": {}}}\n')
    repo.commit("feat: schema change without version edit")
    assert check_values(repo.path, cfg, base, "HEAD").violations == []


def test_guard_skips_stream_whose_source_is_absent_at_base(repo, cfg):
    repo.write("main.go", "x\n")
    base = repo.commit("chore: before adoption")
    seed(repo)  # the adopting PR adds every version file
    r = check_values(repo.path, cfg, base, "HEAD")
    assert r.violations == []
    assert r.skipped == [
        "server: source .version absent at base (new stream); skipped",
        "schema: source openapi.json absent at base (new stream); skipped",
    ]


def test_run_verify_pass_and_fail(repo, cfg):
    seed(repo)
    assert run_verify(repo.path, cfg) == list(cfg.streams[1].verify)
    repo.write("generated.txt", "stale")
    with pytest.raises(HookError, match="verify command failed"):
        run_verify(repo.path, cfg)


def test_guard_reports_violations_before_verify(repo, cfg):
    base = seed(repo)
    repo.write(".version", '{"major": 9, "minor": 0, "patch": 0}\n')
    repo.write("generated.txt", "stale")
    repo.commit("fix: both wrong")
    with pytest.raises(GuardError, match=r"\.version changed"):
        guard(repo.path, cfg, base, "HEAD")


def test_cli_guard(repo, cfg, capsys):
    from version_bump.cli import main

    repo.write(".github/version-bump.toml", CONFIG)
    base = seed(repo)
    repo.write("main.go", "x\n")
    repo.commit("fix: code only")
    assert main(["--repo", str(repo.path), "guard", "--base", base]) == 0
    assert capsys.readouterr().out.startswith("OK: version state untouched (2 stream(s) checked)")
    repo.write(".version", '{"major": 9, "minor": 0, "patch": 0}\n')
    repo.commit("fix: hand bump")
    assert main(["--repo", str(repo.path), "guard", "--base", base, "--head", "HEAD"]) == 1
    assert ".version changed 1.8.16 -> 9.0.0" in capsys.readouterr().err
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_guard.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'version_bump.guard'`.

- [ ] **Step 3: Implement guard.py**

```python
"""PR guard: version state may only change in the post-merge bump commit (spec: CLI `guard`)."""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from version_bump import gitops
from version_bump.config import Config
from version_bump.errors import GuardError, HookError
from version_bump.formats import FileSpec, read_full, read_partial

_SUFFIX = "; only the post-merge bump may write it"


@dataclass
class GuardResult:
    violations: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


def _value_text(repo: Path, ref: str, spec: FileSpec, full: bool) -> str | None:
    text = gitops.show_file(repo, ref, spec.file)
    if text is None:
        return None
    return str(read_full(text, spec)) if full else read_partial(text, spec).text


def check_values(repo: Path, config: Config, base: str, head: str) -> GuardResult:
    base = gitops.rev_parse(repo, base)
    head = gitops.rev_parse(repo, head)
    result = GuardResult()
    for stream in config.streams:
        src_base = _value_text(repo, base, stream.source, full=True)
        if src_base is None:
            result.skipped.append(f"{stream.name}: source {stream.source.file} absent at base (new stream); skipped")
            continue
        src_head = _value_text(repo, head, stream.source, full=True)
        if src_head != src_base:
            result.violations.append(
                f"{stream.name}: {stream.source.file} changed {src_base} -> {src_head}{_SUFFIX}"
            )
        for target in stream.targets:
            t_base = _value_text(repo, base, target, full=False)
            if t_base is None:
                result.skipped.append(f"{stream.name}: target {target.file} absent at base; skipped")
                continue
            t_head = _value_text(repo, head, target, full=False)
            if t_head != t_base:
                result.violations.append(
                    f"{stream.name}: {target.file} changed {t_base} -> {t_head}{_SUFFIX}"
                )
    return result


def run_verify(repo: Path, config: Config) -> list[str]:
    ran: list[str] = []
    for stream in config.streams:
        for cmd in stream.verify:
            print(f"+ {cmd}", file=sys.stderr, flush=True)
            proc = subprocess.run(cmd, shell=True, cwd=repo, stdin=subprocess.DEVNULL, check=False)
            if proc.returncode != 0:
                raise HookError(f"stream {stream.name!r}: verify command failed (exit {proc.returncode}): {cmd}")
            ran.append(cmd)
    return ran


def guard(repo: Path, config: Config, base: str, head: str = "HEAD") -> GuardResult:
    result = check_values(repo, config, base, head)
    if result.violations:
        raise GuardError("\n".join(result.violations))
    run_verify(repo, config)
    return result
```

- [ ] **Step 4: Add the `guard` subcommand to cli.py**

```python
from version_bump.guard import guard


def cmd_guard(args: argparse.Namespace) -> int:
    repo, config = _repo_and_config(args)
    result = guard(repo, config, args.base, args.head)
    checked = len(config.streams) - sum(1 for s in result.skipped if "(new stream)" in s)
    print(f"OK: version state untouched ({checked} stream(s) checked)")
    for note in result.skipped:
        print(f"note: {note}")
    return 0


    # in build_parser():
    p = sub.add_parser("guard", help="fail if a PR changed version state; then run verify commands")
    p.add_argument("--base", required=True, help="merge-base commit with the default branch")
    p.add_argument("--head", default="HEAD")
    p.set_defaults(func=cmd_guard)
```

The `main()` error path already prints `error: <message>`; a multi-line `GuardError` therefore prints `error: ` followed by one violation per line, which is what the workflow surfaces.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest && uv run ruff check . && uv run ruff format --check .`
Expected: all passed. (`test_cli_error_prints_one_line_and_exits_1` from Task 8 still holds: that error is single-line.)

- [ ] **Step 6: Commit**

```bash
git add src/version_bump/guard.py src/version_bump/cli.py tests/test_guard.py
git commit -m "feat(guard): compare version values between base and head and run verify commands"
```

---

### Task 11: `tag`: idempotent, never-moving release tags

**Files:**
- Create: `src/version_bump/tags.py`
- Modify: `src/version_bump/cli.py` (add `tag`)
- Test: `tests/test_tags.py`

**Interfaces:**
- Consumes: `Plan` (Task 8); `gitops.tag_target`, `gitops.create_tag`, `gitops.rev_parse` (Task 7); `TagError` (Task 1).
- Produces: `plan_tags(plan: Plan) -> list[str]` (the non-null `tag` of each bumped stream, in order); `ensure_tags(repo: Path, tags: list[str], sha: str) -> TagOutcome` with `TagOutcome(created: list[str], existing: list[str])`; raises `TagError("tag <t> already exists at <sha7>, not <sha7>; tags never move")` on a conflict, having created nothing (conflicts are checked for all tags first).
- CLI: `version-bump tag --plan FILE [--commit SHA]` (default `HEAD`) prints JSON `{"created": [...], "existing": [...], "all": [...]}`; the workflow pushes `all` one ref at a time.

Local only: the CLI creates tags in the local repo; pushing is the workflow's job. With `fetch-tags: true` the local tag namespace mirrors the remote at checkout time, so a remote tag on a different commit shows up as a local conflict.

- [ ] **Step 1: Write the failing tests**

`tests/test_tags.py`:

```python
import json

import pytest

from version_bump import gitops
from version_bump.errors import TagError
from version_bump.plan import Plan, StreamPlan
from version_bump.tags import ensure_tags, plan_tags


def fake_plan(sha, *tags):
    return Plan(
        ref=sha,
        base=sha,
        pending=[],
        streams=[StreamPlan(f"s{i}", "1.0.0", "1.0.1", t, [], []) for i, t in enumerate(tags)],
        commit_subject="chore(version): bump",
        commit_body="",
    )


def test_plan_tags_skips_null(repo):
    assert plan_tags(fake_plan("x", "v1.0.1", None, "lib/v1.0.1")) == ["v1.0.1", "lib/v1.0.1"]


def test_create_then_idempotent(repo):
    repo.write("a", "0")
    sha = repo.commit("chore: base")
    out = ensure_tags(repo.path, ["v1.0.1", "lib/v1.0.1"], sha)
    assert out.created == ["v1.0.1", "lib/v1.0.1"] and out.existing == []
    again = ensure_tags(repo.path, ["v1.0.1", "lib/v1.0.1"], sha)
    assert again.created == [] and again.existing == ["v1.0.1", "lib/v1.0.1"]
    assert gitops.tag_target(repo.path, "v1.0.1") == sha


def test_conflicting_tag_is_error_and_creates_nothing(repo):
    repo.write("a", "0")
    old = repo.commit("chore: old")
    gitops.create_tag(repo.path, "v1.0.1", old)
    repo.write("a", "1")
    new = repo.commit("chore: new")
    with pytest.raises(TagError, match=f"v1.0.1 already exists at {old[:7]}, not {new[:7]}; tags never move"):
        ensure_tags(repo.path, ["fresh", "v1.0.1"], new)
    assert gitops.tag_target(repo.path, "fresh") is None
    assert gitops.tag_target(repo.path, "v1.0.1") == old


def test_cli_tag(repo, capsys):
    from version_bump.cli import main

    repo.write(".github/version-bump.toml", '[[stream]]\nname = "s0"\nsource = { file = "v.json", format = "json-semver" }\ntag = "v{version}"\n')
    repo.write("v.json", '{"major": 1, "minor": 0, "patch": 1}')
    sha = repo.commit("chore(version): bump s0 to 1.0.1")
    plan_file = repo.path / "plan.json"
    plan_file.write_text(fake_plan(sha, "v1.0.1").to_json())
    assert main(["--repo", str(repo.path), "tag", "--plan", str(plan_file)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out == {"created": ["v1.0.1"], "existing": [], "all": ["v1.0.1"]}
    assert gitops.tag_target(repo.path, "v1.0.1") == sha
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_tags.py`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement tags.py**

```python
"""Release tags: created once at the bump commit, idempotent, never moved."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from version_bump import gitops
from version_bump.errors import TagError
from version_bump.plan import Plan


@dataclass
class TagOutcome:
    created: list[str] = field(default_factory=list)
    existing: list[str] = field(default_factory=list)

    @property
    def all(self) -> list[str]:
        return self.created + self.existing


def plan_tags(plan: Plan) -> list[str]:
    return [s.tag for s in plan.streams if s.tag]


def ensure_tags(repo: Path, tags: list[str], sha: str) -> TagOutcome:
    sha = gitops.rev_parse(repo, sha)
    outcome = TagOutcome()
    todo: list[str] = []
    for tag in tags:
        at = gitops.tag_target(repo, tag)
        if at is None:
            todo.append(tag)
        elif at == sha:
            outcome.existing.append(tag)
        else:
            raise TagError(f"tag {tag} already exists at {at[:7]}, not {sha[:7]}; tags never move")
    for tag in todo:
        gitops.create_tag(repo, tag, sha)
        outcome.created.append(tag)
    return outcome
```

- [ ] **Step 4: Add the `tag` subcommand to cli.py**

```python
import json

from version_bump.tags import ensure_tags, plan_tags


def cmd_tag(args: argparse.Namespace) -> int:
    repo, _ = _repo_and_config(args)
    plan = _load_plan(args.plan)
    outcome = ensure_tags(repo, plan_tags(plan), args.commit)
    print(json.dumps({"created": outcome.created, "existing": outcome.existing, "all": outcome.all}))
    return 0


    # in build_parser():
    p = sub.add_parser("tag", help="create the plan's release tags locally (idempotent; never moves a tag)")
    p.add_argument("--plan", required=True, help="plan JSON file, or - for stdin")
    p.add_argument("--commit", default="HEAD", help="commit to tag (default HEAD)")
    p.set_defaults(func=cmd_tag)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest && uv run ruff check . && uv run ruff format --check .`
Expected: all passed.

- [ ] **Step 6: Commit**

```bash
git add src/version_bump/tags.py src/version_bump/cli.py tests/test_tags.py
git commit -m "feat(tags): create release tags idempotently without ever moving one"
```

---

### Task 12: `doctor`: read-only repo-settings check with fix commands

**Files:**
- Create: `src/version_bump/doctor.py`
- Create: `tests/fixtures/doctor/repo_ok.json`, `repo_bad.json`, `rulesets_ok.json`, `ruleset_ok.json`, `rulesets_none.json`, `ruleset_bad.json`
- Modify: `src/version_bump/cli.py` (add `doctor`)
- Test: `tests/test_doctor.py`

**Interfaces:**
- Consumes: `load_config` (Task 6).
- Produces: `Fetch = Callable[[str], Any]` (a function taking a `gh api` path like `repos/o/r` and returning parsed JSON); `gh_fetch(path) -> Any` (default: `gh api <path>` via subprocess, `stdin=DEVNULL`); `Finding(ok: bool, check: str, detail: str, fix: str | None)`; `run_doctor(repo_slug: str, config_path: Path, fetch: Fetch, app_id: int | None, check_name: str = "Version Guard") -> list[Finding]`; `detect_repo_slug(repo: Path) -> str | None` (parses `GITHUB_REPOSITORY` or `git remote get-url origin`); `format_report(findings) -> str`.
- CLI: `version-bump doctor [--repo-slug OWNER/REPO] [--app-id N] [--check-name NAME]`; exit 0 when every finding is ok, else 1. `--app-id` defaults to env `VERSION_BUMP_APP_ID` if set.

Checks and the fix each prints:
1. Config validity (`load_config`): fix = the error text.
2. `GET repos/{slug}`: `allow_squash_merge == true`, `allow_merge_commit == false`, `allow_rebase_merge == false`, `squash_merge_commit_title == "PR_TITLE"`. Fix: `gh api -X PATCH repos/{slug} -F allow_squash_merge=true -F allow_merge_commit=false -F allow_rebase_merge=false -f squash_merge_commit_title=PR_TITLE -f squash_merge_commit_message=PR_BODY`.
3. `GET repos/{slug}/rulesets?targets=branch` then `GET repos/{slug}/rulesets/{id}` for each; pick the active rulesets whose `conditions.ref_name.include` contains `~DEFAULT_BRANCH` or `refs/heads/{default_branch}`. Across them:
   - **Bypass actor:** exactly one bypass actor overall, `actor_type == "Integration"`, `actor_id == app_id`, `bypass_mode == "always"`. If `app_id` is None, the finding is `ok=False` with detail "pass --app-id to verify the bypass actor" only when the actors are not exactly one Integration.
   - **Required check:** some ruleset has a `required_status_checks` rule whose `parameters.required_status_checks[].context` equals `check_name` or ends with `" / " + check_name` (reusable-workflow checks are named `<caller job> / <called job>`).
   - Fix: a complete `gh api -X PUT repos/{slug}/rulesets/{id} --input - <<'JSON' ... JSON` heredoc with the first matching ruleset's JSON, `bypass_actors` replaced by the single App actor and the required-check rule added/updated. When no default-branch ruleset exists, the fix is a `POST repos/{slug}/rulesets` heredoc creating one (`enforcement: active`, `target: branch`, include `~DEFAULT_BRANCH`, rules `pull_request` + `required_status_checks` with the check, `deletion`, `non_fast_forward`).

- [ ] **Step 1: Write the fixtures**

`tests/fixtures/doctor/repo_ok.json`:

```json
{"full_name": "ericfitz/example", "default_branch": "main", "allow_squash_merge": true,
 "allow_merge_commit": false, "allow_rebase_merge": false, "squash_merge_commit_title": "PR_TITLE"}
```

`tests/fixtures/doctor/repo_bad.json`:

```json
{"full_name": "ericfitz/example", "default_branch": "main", "allow_squash_merge": true,
 "allow_merge_commit": true, "allow_rebase_merge": false, "squash_merge_commit_title": "COMMIT_OR_PR_TITLE"}
```

`tests/fixtures/doctor/rulesets_ok.json`:

```json
[{"id": 42, "name": "main", "target": "branch", "enforcement": "active"}]
```

`tests/fixtures/doctor/rulesets_none.json`:

```json
[]
```

`tests/fixtures/doctor/ruleset_ok.json`:

```json
{"id": 42, "name": "main", "target": "branch", "enforcement": "active",
 "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
 "bypass_actors": [{"actor_id": 123456, "actor_type": "Integration", "bypass_mode": "always"}],
 "rules": [
   {"type": "pull_request", "parameters": {"required_approving_review_count": 0}},
   {"type": "required_status_checks", "parameters": {"strict_required_status_checks_policy": false,
     "required_status_checks": [{"context": "guard / Version Guard"}]}}
 ]}
```

`tests/fixtures/doctor/ruleset_bad.json`:

```json
{"id": 42, "name": "main", "target": "branch", "enforcement": "active",
 "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
 "bypass_actors": [{"actor_id": 15368, "actor_type": "Integration", "bypass_mode": "always"},
                   {"actor_id": 5, "actor_type": "RepositoryRole", "bypass_mode": "always"}],
 "rules": [
   {"type": "pull_request", "parameters": {"required_approving_review_count": 0}},
   {"type": "required_status_checks", "parameters": {"strict_required_status_checks_policy": false,
     "required_status_checks": [{"context": "Version Check"}]}}
 ]}
```

- [ ] **Step 2: Write the failing tests**

`tests/test_doctor.py`:

```python
import json
from pathlib import Path

import pytest

from version_bump.doctor import Finding, detect_repo_slug, format_report, run_doctor

FIX = Path(__file__).parent / "fixtures" / "doctor"
CFG = '[[stream]]\nname = "s"\nsource = { file = "v.json", format = "json-semver" }\n'


def fetcher(repo="repo_ok", rulesets="rulesets_ok", ruleset="ruleset_ok"):
    table = {
        "repos/ericfitz/example": f"{repo}.json",
        "repos/ericfitz/example/rulesets?targets=branch": f"{rulesets}.json",
        "repos/ericfitz/example/rulesets/42": f"{ruleset}.json",
    }
    calls = []

    def fetch(path):
        calls.append(path)
        return json.loads((FIX / table[path]).read_text())

    fetch.calls = calls
    return fetch


@pytest.fixture
def cfg_path(tmp_path):
    p = tmp_path / "version-bump.toml"
    p.write_text(CFG)
    return p


def test_all_ok(cfg_path):
    fetch = fetcher()
    findings = run_doctor("ericfitz/example", cfg_path, fetch, app_id=123456)
    assert all(f.ok for f in findings), format_report(findings)
    assert [f.check for f in findings] == ["config", "merge settings", "bypass actor", "required check"]
    assert all(p.startswith("repos/") for p in fetch.calls)  # read-only GETs only


def test_bad_settings_print_fix_commands(cfg_path):
    findings = run_doctor("ericfitz/example", cfg_path, fetcher(repo="repo_bad", ruleset="ruleset_bad"), app_id=123456)
    by = {f.check: f for f in findings}
    assert not by["merge settings"].ok
    assert "gh api -X PATCH repos/ericfitz/example" in by["merge settings"].fix
    assert "squash_merge_commit_title=PR_TITLE" in by["merge settings"].fix
    assert not by["bypass actor"].ok and "15368" in by["bypass actor"].detail
    assert "gh api -X PUT repos/ericfitz/example/rulesets/42" in by["bypass actor"].fix
    fixed = json.loads(by["bypass actor"].fix.split("<<'JSON'\n", 1)[1].rsplit("\nJSON", 1)[0])
    assert fixed["bypass_actors"] == [{"actor_id": 123456, "actor_type": "Integration", "bypass_mode": "always"}]
    contexts = [c["context"] for r in fixed["rules"] if r["type"] == "required_status_checks" for c in r["parameters"]["required_status_checks"]]
    assert "guard / Version Guard" in contexts
    assert not by["required check"].ok and "Version Guard" in by["required check"].detail


def test_no_ruleset_prints_post(cfg_path):
    findings = run_doctor("ericfitz/example", cfg_path, fetcher(rulesets="rulesets_none"), app_id=123456)
    by = {f.check: f for f in findings}
    assert not by["bypass actor"].ok
    assert "gh api -X POST repos/ericfitz/example/rulesets" in by["bypass actor"].fix


def test_missing_app_id_cannot_verify_actor(cfg_path):
    findings = run_doctor("ericfitz/example", cfg_path, fetcher(), app_id=None)
    by = {f.check: f for f in findings}
    assert by["bypass actor"].ok  # exactly one Integration actor; id unverified
    assert "--app-id" in by["bypass actor"].detail


def test_invalid_config_is_a_finding(tmp_path):
    p = tmp_path / "bad.toml"
    p.write_text("[[stream]]\nname = 'x'\n")
    findings = run_doctor("ericfitz/example", p, fetcher(), app_id=123456)
    assert not findings[0].ok and findings[0].check == "config"


def test_format_report():
    text = format_report([Finding(True, "a", "fine", None), Finding(False, "b", "bad", "gh api x")])
    assert "OK   a: fine" in text and "FAIL b: bad" in text and "  fix: gh api x" in text


def test_detect_repo_slug(repo, monkeypatch):
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    assert detect_repo_slug(repo.path) is None  # no remote in scratch repos, by design
    monkeypatch.setenv("GITHUB_REPOSITORY", "ericfitz/example")
    assert detect_repo_slug(repo.path) == "ericfitz/example"
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/test_doctor.py`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 4: Implement doctor.py**

```python
"""Read-only check of an adopting repo's settings, with the exact fix commands (spec: CLI `doctor`)."""

from __future__ import annotations

import copy
import json
import os
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from version_bump import gitops
from version_bump.config import load_config
from version_bump.errors import VersionBumpError

Fetch = Callable[[str], Any]
_SLUG_RE = re.compile(r"github\.com[:/]([^/]+)/([^/]+?)(?:\.git)?/?$")


@dataclass
class Finding:
    ok: bool
    check: str
    detail: str
    fix: str | None = None


def gh_fetch(path: str) -> Any:
    proc = subprocess.run(
        ["gh", "api", path],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise VersionBumpError(f"gh api {path} failed: {proc.stderr.strip()}")
    return json.loads(proc.stdout)


def detect_repo_slug(repo: Path) -> str | None:
    env = os.environ.get("GITHUB_REPOSITORY")
    if env:
        return env
    url = gitops.git(repo, "remote", "get-url", "origin", check=False)
    m = _SLUG_RE.search(url)
    return f"{m.group(1)}/{m.group(2)}" if m else None


def _heredoc(method: str, path: str, body: dict[str, Any]) -> str:
    return f"gh api -X {method} {path} --input - <<'JSON'\n{json.dumps(body, indent=2)}\nJSON"


def _check_merge_settings(slug: str, repo: dict[str, Any]) -> Finding:
    want = {
        "allow_squash_merge": True,
        "allow_merge_commit": False,
        "allow_rebase_merge": False,
        "squash_merge_commit_title": "PR_TITLE",
    }
    wrong = {k: repo.get(k) for k, v in want.items() if repo.get(k) != v}
    fix = (
        f"gh api -X PATCH repos/{slug} -F allow_squash_merge=true -F allow_merge_commit=false "
        "-F allow_rebase_merge=false -f squash_merge_commit_title=PR_TITLE "
        "-f squash_merge_commit_message=PR_BODY"
    )
    if wrong:
        return Finding(False, "merge settings", f"not squash-only with PR_TITLE subjects: {wrong}", fix)
    return Finding(True, "merge settings", "squash-only merges with PR_TITLE subjects")


def _default_branch_rulesets(slug: str, default_branch: str, fetch: Fetch) -> list[dict[str, Any]]:
    out = []
    for item in fetch(f"repos/{slug}/rulesets?targets=branch"):
        rs = fetch(f"repos/{slug}/rulesets/{item['id']}")
        if rs.get("enforcement") != "active":
            continue
        include = rs.get("conditions", {}).get("ref_name", {}).get("include", [])
        if "~DEFAULT_BRANCH" in include or f"refs/heads/{default_branch}" in include:
            out.append(rs)
    return out


def _check_contexts(rulesets: list[dict[str, Any]]) -> list[str]:
    ctx = []
    for rs in rulesets:
        for rule in rs.get("rules", []):
            if rule.get("type") == "required_status_checks":
                ctx += [c["context"] for c in rule["parameters"].get("required_status_checks", [])]
    return ctx


def _matches_check(context: str, check_name: str) -> bool:
    return context == check_name or context.endswith(" / " + check_name)


def _fixed_ruleset(rs: dict[str, Any], app_id: int | None, check_context: str) -> dict[str, Any]:
    fixed = copy.deepcopy(rs)
    for k in ("id", "node_id", "_links", "created_at", "updated_at", "source", "source_type", "current_user_can_bypass"):
        fixed.pop(k, None)
    fixed["bypass_actors"] = [
        {"actor_id": app_id if app_id is not None else 0, "actor_type": "Integration", "bypass_mode": "always"}
    ]
    rules = [r for r in fixed.get("rules", []) if r.get("type") != "required_status_checks"]
    existing = [r for r in fixed.get("rules", []) if r.get("type") == "required_status_checks"]
    checks = existing[0]["parameters"].get("required_status_checks", []) if existing else []
    if not any(_matches_check(c["context"], check_context.split(" / ")[-1]) for c in checks):
        checks = checks + [{"context": check_context}]
    rules.append(
        {
            "type": "required_status_checks",
            "parameters": {"strict_required_status_checks_policy": False, "required_status_checks": checks},
        }
    )
    fixed["rules"] = rules
    return fixed


def _new_ruleset(app_id: int | None, check_context: str) -> dict[str, Any]:
    return {
        "name": "default-branch",
        "target": "branch",
        "enforcement": "active",
        "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
        "bypass_actors": [
            {"actor_id": app_id if app_id is not None else 0, "actor_type": "Integration", "bypass_mode": "always"}
        ],
        "rules": [
            {"type": "deletion"},
            {"type": "non_fast_forward"},
            {"type": "pull_request", "parameters": {"required_approving_review_count": 0,
                                                    "dismiss_stale_reviews_on_push": False,
                                                    "require_code_owner_review": False,
                                                    "require_last_push_approval": False,
                                                    "required_review_thread_resolution": False}},
            {"type": "required_status_checks", "parameters": {"strict_required_status_checks_policy": False,
                                                              "required_status_checks": [{"context": check_context}]}},
        ],
    }


def run_doctor(
    repo_slug: str, config_path: Path, fetch: Fetch, app_id: int | None, check_name: str = "Version Guard"
) -> list[Finding]:
    findings: list[Finding] = []
    try:
        load_config(config_path)
        findings.append(Finding(True, "config", f"{config_path} is valid"))
    except VersionBumpError as exc:
        findings.append(Finding(False, "config", str(exc), "fix the config file"))

    repo = fetch(f"repos/{repo_slug}")
    findings.append(_check_merge_settings(repo_slug, repo))

    default_branch = repo.get("default_branch", "main")
    rulesets = _default_branch_rulesets(repo_slug, default_branch, fetch)
    check_context = f"guard / {check_name}"
    if not rulesets:
        fix = _heredoc("POST", f"repos/{repo_slug}/rulesets", _new_ruleset(app_id, check_context))
        findings.append(Finding(False, "bypass actor", f"no active ruleset targets {default_branch}", fix))
        findings.append(Finding(False, "required check", f"no ruleset requires {check_name!r}", fix))
        return findings

    actors = [a for rs in rulesets for a in rs.get("bypass_actors", [])]
    fix = _heredoc("PUT", f"repos/{repo_slug}/rulesets/{rulesets[0]['id']}", _fixed_ruleset(rulesets[0], app_id, check_context))
    one_integration = len(actors) == 1 and actors[0].get("actor_type") == "Integration" and actors[0].get("bypass_mode") == "always"
    if not one_integration:
        findings.append(Finding(False, "bypass actor", f"expected exactly one Integration bypass actor (the App), found {actors}", fix))
    elif app_id is None:
        findings.append(Finding(True, "bypass actor", f"one Integration actor {actors[0]['actor_id']}; pass --app-id to verify it is the App"))
    elif actors[0].get("actor_id") != app_id:
        findings.append(Finding(False, "bypass actor", f"bypass actor is {actors[0]['actor_id']}, expected App {app_id}", fix))
    else:
        findings.append(Finding(True, "bypass actor", f"App {app_id} is the only bypass actor"))

    contexts = _check_contexts(rulesets)
    if any(_matches_check(c, check_name) for c in contexts):
        findings.append(Finding(True, "required check", f"{check_name!r} is required"))
    else:
        findings.append(Finding(False, "required check", f"{check_name!r} is not a required check (found {contexts})", fix))
    return findings


def format_report(findings: list[Finding]) -> str:
    lines = []
    for f in findings:
        lines.append(f"{'OK  ' if f.ok else 'FAIL'} {f.check}: {f.detail}")
        if not f.ok and f.fix:
            lines.append("  fix: " + f.fix.replace("\n", "\n       "))
    return "\n".join(lines)
```

- [ ] **Step 5: Add the `doctor` subcommand to cli.py**

```python
import os

from version_bump.doctor import detect_repo_slug, format_report, gh_fetch, run_doctor


def cmd_doctor(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    slug = args.repo_slug or detect_repo_slug(repo)
    if not slug:
        raise VersionBumpError("cannot determine OWNER/REPO; pass --repo-slug")
    app_id = args.app_id if args.app_id is not None else os.environ.get("VERSION_BUMP_APP_ID")
    findings = run_doctor(slug, repo / args.config, gh_fetch, int(app_id) if app_id else None, args.check_name)
    print(format_report(findings))
    return 0 if all(f.ok for f in findings) else 1


    # in build_parser():
    p = sub.add_parser("doctor", help="check repo settings read-only via gh api; print fix commands")
    p.add_argument("--repo-slug", help="OWNER/REPO (default: $GITHUB_REPOSITORY or the origin remote)")
    p.add_argument("--app-id", type=int, help="GitHub App id expected as the ruleset bypass actor")
    p.add_argument("--check-name", default="Version Guard")
    p.set_defaults(func=cmd_doctor)
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest && uv run ruff check . && uv run ruff format --check .`
Expected: all passed.

- [ ] **Step 7: Commit**

```bash
git add src/version_bump/doctor.py src/version_bump/cli.py tests/test_doctor.py tests/fixtures/doctor
git commit -m "feat(doctor): check merge settings, bypass actor and required check with fix commands"
```

---

### Task 13: The reusable workflows (`bump.yml`, `guard.yml`), the alias workflow, and their checks

**Files:**
- Create: `.github/workflows/bump.yml`, `.github/workflows/guard.yml`, `.github/workflows/release-alias.yml`
- Test: `tests/test_workflows.py` (actionlint), `tests/test_release_tag.py` (embedded tag constant == `v{project.version}`)

**Interfaces:**
- Consumes: the CLI (`plan`, `apply`, `hooks`, `tag`, `guard`) and the plan JSON contract (`.streams | length`, `.commit_subject`, `.commit_body`, tag output `.all[]`).
- Produces: reusable workflow `bump.yml` with inputs `setup` (string, default `""`), `app_slug` (string, default `ericfitz-version-bump`), `bot_ref` (string, default `""` = the embedded constant), `config` (string, default `.github/version-bump.toml`) and required secrets `VERSION_BUMP_APP_ID`, `VERSION_BUMP_APP_PRIVATE_KEY`; reusable workflow `guard.yml` with inputs `bot_ref`, `config` and no secrets; the constant `VERSION_BUMP_BOT_REF: v0.1.0` in both (kept in sync by the self-adoption stream in Task 14).

Decisions baked into the workflows (each is also recorded in the README in Task 14):
- **Skip guard** = `github.actor == '<app_slug>[bot]'` (a push made with an App installation token is attributed to the App's bot user) AND `startsWith(github.event.head_commit.message, 'chore(version)')`. `head_commit` is null on `workflow_dispatch`, so `startsWith` is false and a manual run always proceeds (it then usually finds nothing pending).
- **Bot checkout:** the caller repo is checked out at the default branch into the workspace; the bot is checked out into `.version-bump-bot/` with the default `GITHUB_TOKEN` (the bot repo must be public, or private with Actions access granted; a private repo would additionally need a readable token here). `uv run --no-dev --project .version-bump-bot` keeps the cwd at the caller repo (and skips the dev group), so the CLI sees the adopter's files.
- **`setup` grammar:** comma-separated tokens. `go` -> `actions/setup-go` with `go-version-file: go.mod`; `node` -> `actions/setup-node` with `node-version-file: package.json` (needs `engines.node`); `pnpm` -> `pnpm/action-setup` (reads `packageManager`) plus node; `uv` -> nothing extra (uv is always set up). A token containing `@` is a `go install`: `oapi-codegen@v2.7.1` is an alias for `github.com/oapi-codegen/oapi-codegen/v2/cmd/oapi-codegen@v2.7.1`; any other `name@ver` must give a full module path (contains `/`). Token matching is delimiter-wrapped (`contains(format(',{0},', inputs.setup), ',go,')`) so `golangci-lint@...` does not switch Go on by accident.
- **Commit:** `git add -u` (tracked files only, so the bot checkout is never staged; hooks must only modify tracked files). The message comes from the plan via `git commit -F` (never `-m "${{ ... }}"`). No `[skip ci]`: the adopter's own CI should still run on the bump commit, and the two no-cascade guards make it unnecessary.
- **Push rejection** and **tags** exactly as Global Constraints say. Tags are pushed one ref at a time (`refs/tags/<t>`), never `--tags`.
- **Untestable locally:** the push/rejection branch and the token mint cannot run without a remote. They are validated by actionlint and by the first self-adoption run (Task 14 / release process). Say so in the PR description; do not add a local "remote" to test them.

- [ ] **Step 1: Write the failing checks**

`tests/test_workflows.py`:

```python
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.yml"))


def test_expected_workflows_exist():
    names = {p.name for p in WORKFLOWS}
    assert {"ci.yml", "bump.yml", "guard.yml", "release-alias.yml"} <= names


def test_actionlint_passes():
    exe = shutil.which("actionlint")
    if exe is None:
        if os.environ.get("ACTIONLINT_REQUIRED") == "1":
            pytest.fail("actionlint is required in CI but was not found on PATH")
        pytest.skip("actionlint not installed; CI runs it (ACTIONLINT_REQUIRED=1)")
    proc = subprocess.run(
        [exe, *map(str, WORKFLOWS)],
        cwd=ROOT,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_bump_workflow_never_interpolates_plan_strings_into_shell():
    text = (ROOT / ".github/workflows/bump.yml").read_text()
    assert 'git commit -F' in text
    assert '-m "${{' not in text
    assert "private-key: ${{ secrets.VERSION_BUMP_APP_PRIVATE_KEY }}" in text
    assert "echo ${{ secrets" not in text
```

`tests/test_release_tag.py`:

```python
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONST_RE = re.compile(r"^\s*VERSION_BUMP_BOT_REF: v(\d+\.\d+\.\d+)\s*$", re.MULTILINE)


def project_version() -> str:
    return tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]


def test_embedded_release_tag_matches_pyproject_in_every_reusable_workflow():
    for name in ("bump.yml", "guard.yml"):
        text = (ROOT / ".github" / "workflows" / name).read_text()
        found = CONST_RE.findall(text)
        assert len(found) == 1, f"{name}: expected exactly one VERSION_BUMP_BOT_REF, found {found}"
        assert found[0] == project_version(), f"{name} embeds v{found[0]} but pyproject.toml says {project_version()}"
```

Run: `uv run pytest tests/test_workflows.py tests/test_release_tag.py`
Expected: FAIL (`bump.yml` etc. do not exist yet).

- [ ] **Step 2: Write `.github/workflows/bump.yml`**

```yaml
# Reusable post-merge version bump. Callers: see README "Adopting a repo".
# Design: docs/superpowers/specs/2026-10-03-version-bump-bot-design.md (Workflows / bump).
#
# No cascade, two independent guards:
#   1. the job is skipped when the push actor is the App's bot user and the head
#      commit subject starts with "chore(version)";
#   2. `version-bump plan` folds only commits after the last one that changed a
#      stream's source VALUE, and the bump commit changes those values.
#
# The release tag of THIS workflow is embedded below (a called workflow cannot
# read its own ref). The self-adoption stream rewrites it on every release and
# CI checks it against pyproject.toml.
name: version-bump-bot bump

on:
  workflow_call:
    inputs:
      setup:
        description: >-
          Comma-separated toolchains the `after` hooks need: go, node, pnpm, uv, plus
          name@version go-install entries (oapi-codegen@v2.7.1, or a full module path).
        type: string
        default: ""
      app_slug:
        description: Slug of the GitHub App whose bot user pushes the bump commit.
        type: string
        default: ericfitz-version-bump
      bot_ref:
        description: Ref of ericfitz/version-bump-bot to run (default is the embedded release tag).
        type: string
        default: ""
      config:
        description: Path of the version-bump config in the calling repo.
        type: string
        default: .github/version-bump.toml
    secrets:
      VERSION_BUMP_APP_ID:
        required: true
      VERSION_BUMP_APP_PRIVATE_KEY:
        required: true

env:
  VERSION_BUMP_BOT_REF: v0.1.0
  BOT_DIR: .version-bump-bot

permissions:
  contents: read

jobs:
  bump:
    name: Version Bump
    # Skip guard (1): the bot's own bump commit never starts a bump.
    if: >-
      ${{ !(github.actor == format('{0}[bot]', inputs.app_slug)
            && startsWith(github.event.head_commit.message, 'chore(version)')) }}
    runs-on: ubuntu-latest
    concurrency:
      group: version-bump-${{ github.repository }}
      cancel-in-progress: false
    env:
      CONFIG: ${{ inputs.config }}
      PLAN: ${{ runner.temp }}/plan.json
    steps:
      - name: Mint an App installation token
        id: token
        uses: actions/create-github-app-token@v2
        with:
          app-id: ${{ secrets.VERSION_BUMP_APP_ID }}
          private-key: ${{ secrets.VERSION_BUMP_APP_PRIVATE_KEY }}

      - name: Check out the default branch (full history and tags)
        uses: actions/checkout@v5
        with:
          ref: ${{ github.event.repository.default_branch }}
          fetch-depth: 0
          fetch-tags: true
          token: ${{ steps.token.outputs.token }}
          persist-credentials: true

      - name: Check out version-bump-bot
        uses: actions/checkout@v5
        with:
          repository: ericfitz/version-bump-bot
          ref: ${{ inputs.bot_ref || env.VERSION_BUMP_BOT_REF }}
          path: ${{ env.BOT_DIR }}
          persist-credentials: false

      - name: Set up uv
        uses: astral-sh/setup-uv@v6
        with:
          python-version: "3.12"

      - name: Plan
        id: plan
        run: |
          set -euo pipefail
          uv run --no-dev --project "$BOT_DIR" version-bump --config "$CONFIG" plan > "$PLAN"
          cat "$PLAN"
          echo "bumped=$(jq '.streams | length' "$PLAN")" >> "$GITHUB_OUTPUT"
          if [ "$(jq '.streams | length' "$PLAN")" = "0" ]; then
            echo "::notice::Nothing to bump."
          fi

      - name: Set up Go
        if: steps.plan.outputs.bumped != '0' && contains(format(',{0},', inputs.setup), ',go,')
        uses: actions/setup-go@v5
        with:
          go-version-file: go.mod

      - name: Set up Node
        if: >-
          steps.plan.outputs.bumped != '0'
          && (contains(format(',{0},', inputs.setup), ',node,') || contains(format(',{0},', inputs.setup), ',pnpm,'))
        uses: actions/setup-node@v4
        with:
          node-version-file: package.json

      - name: Set up pnpm
        if: steps.plan.outputs.bumped != '0' && contains(format(',{0},', inputs.setup), ',pnpm,')
        uses: pnpm/action-setup@v4

      - name: Install Go tools named in setup
        if: steps.plan.outputs.bumped != '0' && contains(inputs.setup, '@')
        env:
          SETUP: ${{ inputs.setup }}
        run: |
          set -euo pipefail
          IFS=',' read -r -a items <<<"$SETUP"
          for item in "${items[@]}"; do
            case "$item" in *@*) ;; *) continue ;; esac
            name="${item%@*}"
            ver="${item##*@}"
            case "$name" in
              oapi-codegen) mod="github.com/oapi-codegen/oapi-codegen/v2/cmd/oapi-codegen" ;;
              */*) mod="$name" ;;
              *) echo "::error::setup entry '$item': unknown tool; give a full Go module path"; exit 1 ;;
            esac
            go install "${mod}@${ver}"
          done

      - name: Apply
        if: steps.plan.outputs.bumped != '0'
        run: uv run --no-dev --project "$BOT_DIR" version-bump --config "$CONFIG" apply --plan "$PLAN"

      - name: Run after hooks
        if: steps.plan.outputs.bumped != '0'
        run: uv run --no-dev --project "$BOT_DIR" version-bump --config "$CONFIG" hooks --plan "$PLAN"

      - name: Re-plan the working tree (must be empty)
        if: steps.plan.outputs.bumped != '0'
        run: |
          set -euo pipefail
          uv run --no-dev --project "$BOT_DIR" version-bump --config "$CONFIG" plan --worktree > "$RUNNER_TEMP/replan.json"
          if [ "$(jq '.streams | length' "$RUNNER_TEMP/replan.json")" != "0" ]; then
            echo "::error::The working tree still has a pending bump after apply and hooks; the stream config is not self-consistent."
            cat "$RUNNER_TEMP/replan.json"
            exit 1
          fi

      - name: Commit and push
        id: push
        if: steps.plan.outputs.bumped != '0'
        env:
          GH_TOKEN: ${{ steps.token.outputs.token }}
          APP_SLUG: ${{ steps.token.outputs.app-slug }}
          DEFAULT_BRANCH: ${{ github.event.repository.default_branch }}
        run: |
          set -euo pipefail
          BOT_USER="${APP_SLUG}[bot]"
          BOT_ID="$(gh api "users/${BOT_USER}" --jq .id)"
          git config user.name "$BOT_USER"
          git config user.email "${BOT_ID}+${BOT_USER}@users.noreply.github.com"
          jq -r '.commit_subject + "\n\n" + .commit_body' "$PLAN" > "$RUNNER_TEMP/message.txt"
          git add -u
          git commit -q -F "$RUNNER_TEMP/message.txt"
          git --no-pager log -1 --stat
          if git push origin "HEAD:refs/heads/${DEFAULT_BRANCH}"; then
            echo "pushed=true" >> "$GITHUB_OUTPUT"
            exit 0
          fi
          git fetch origin "$DEFAULT_BRANCH"
          if [ "$(git rev-parse "origin/${DEFAULT_BRANCH}")" != "$(git rev-parse 'HEAD^')" ]; then
            echo "::notice::${DEFAULT_BRANCH} moved during this run; the newer push's own run folds everything."
            echo "pushed=false" >> "$GITHUB_OUTPUT"
            exit 0
          fi
          echo "::error::Push to ${DEFAULT_BRANCH} was rejected although the branch did not move. The GitHub App '${APP_SLUG}' must be the bypass actor on the ${DEFAULT_BRANCH} ruleset (run: version-bump doctor --app-id <APP_ID>)."
          exit 1

      - name: Create and push release tags
        if: steps.plan.outputs.bumped != '0' && steps.push.outputs.pushed == 'true'
        run: |
          set -euo pipefail
          uv run --no-dev --project "$BOT_DIR" version-bump --config "$CONFIG" tag --plan "$PLAN" > "$RUNNER_TEMP/tags.json"
          cat "$RUNNER_TEMP/tags.json"
          jq -r '.all[]' "$RUNNER_TEMP/tags.json" | while IFS= read -r t; do
            git push origin "refs/tags/${t}"
          done
```

- [ ] **Step 3: Write `.github/workflows/guard.yml`**

```yaml
# Reusable PR guard: fails when a PR edits version state that only the
# post-merge bump may write, then runs each stream's `verify` commands.
# It depends on no other job, so it cannot fail transiently. The check
# appears on the PR as "<caller job id> / Version Guard"; with the
# recommended caller job id `guard` that is "guard / Version Guard".
name: version-bump-bot guard

on:
  workflow_call:
    inputs:
      bot_ref:
        description: Ref of ericfitz/version-bump-bot to run (default is the embedded release tag).
        type: string
        default: ""
      config:
        description: Path of the version-bump config in the calling repo.
        type: string
        default: .github/version-bump.toml

env:
  VERSION_BUMP_BOT_REF: v0.1.0
  BOT_DIR: .version-bump-bot

permissions:
  contents: read

jobs:
  guard:
    name: Version Guard
    runs-on: ubuntu-latest
    env:
      CONFIG: ${{ inputs.config }}
      BASE: ${{ github.event.pull_request.base.ref }}
    steps:
      - name: Check out the PR head (full history)
        uses: actions/checkout@v5
        with:
          ref: ${{ github.event.pull_request.head.sha }}
          fetch-depth: 0
          persist-credentials: false

      - name: Fetch the base branch
        run: git fetch --no-tags origin "refs/heads/${BASE}:refs/remotes/origin/${BASE}"

      - name: Check out version-bump-bot
        uses: actions/checkout@v5
        with:
          repository: ericfitz/version-bump-bot
          ref: ${{ inputs.bot_ref || env.VERSION_BUMP_BOT_REF }}
          path: ${{ env.BOT_DIR }}
          persist-credentials: false

      - name: Set up uv
        uses: astral-sh/setup-uv@v6
        with:
          python-version: "3.12"

      - name: Version Guard
        run: |
          set -euo pipefail
          MB="$(git merge-base "origin/${BASE}" HEAD)"
          echo "merge-base: $MB"
          uv run --no-dev --project "$BOT_DIR" version-bump --config "$CONFIG" guard --base "$MB" --head HEAD
```

- [ ] **Step 4: Write `.github/workflows/release-alias.yml`**

```yaml
# Moves the major alias tag (v1) to every new release tag (v1.2.3) of this repo.
# The bot's own `tag` subcommand never moves a tag; this alias is the one
# deliberate exception, and it lives here, outside the bot.
# Pushing v1.2.3 with the App token triggers this workflow; the alias v1 does
# not match the pattern, so it cannot re-trigger itself.
name: Move major alias tag

on:
  push:
    tags:
      - "v[0-9]+.[0-9]+.[0-9]+"

permissions:
  contents: read

jobs:
  alias:
    name: Move major alias
    runs-on: ubuntu-latest
    steps:
      - name: Mint an App installation token
        id: token
        uses: actions/create-github-app-token@v2
        with:
          app-id: ${{ secrets.VERSION_BUMP_APP_ID }}
          private-key: ${{ secrets.VERSION_BUMP_APP_PRIVATE_KEY }}

      - uses: actions/checkout@v5
        with:
          token: ${{ steps.token.outputs.token }}
          persist-credentials: true

      - name: Force-move the alias
        run: |
          set -euo pipefail
          MAJOR="${GITHUB_REF_NAME%%.*}"   # v1.2.3 -> v1
          git tag -f "$MAJOR" "$GITHUB_SHA"
          git push -f origin "refs/tags/${MAJOR}"
          echo "::notice::${MAJOR} -> ${GITHUB_REF_NAME} (${GITHUB_SHA})"
```

- [ ] **Step 5: Run the checks**

Run: `actionlint` (from the repo root, all workflows) then `uv run pytest tests/test_workflows.py tests/test_release_tag.py`
Expected: actionlint clean; both test files pass (`pyproject.toml` is `0.1.0` and both workflows embed `v0.1.0`).

If actionlint complains about `${{ env.BOT_DIR }}` inside `with: path:`, keep the literal `.version-bump-bot` in that `with:` instead and leave `BOT_DIR` for `run:` steps.

- [ ] **Step 6: Commit**

```bash
git add .github/workflows/bump.yml .github/workflows/guard.yml .github/workflows/release-alias.yml tests/test_workflows.py tests/test_release_tag.py
git commit -m "ci: add reusable bump and guard workflows and the major-alias tag workflow"
```

---

### Task 14: Self-adoption config, caller workflow, README with the adoption checklist, local end-to-end test

**Files:**
- Create: `.github/version-bump.toml`, `.github/workflows/version.yml`
- Modify: `README.md` (replace the stub)
- Test: `tests/test_e2e.py`, extend `tests/test_release_tag.py`

**Interfaces:**
- Consumes: everything. The e2e test drives `version_bump.cli.main` through the same sequence `bump.yml` runs (plan -> apply -> hooks -> plan --worktree -> commit -> tag -> re-plan -> guard), locally, with no remote.

- [ ] **Step 1: Write the self-adoption config**

`.github/version-bump.toml`:

```toml
# version-bump-bot's own version stream. The repo IS the bot, so no trigger:
# every non-docs merge bumps. The two reusable workflows embed the release
# tag; they are regex targets so `apply` rewrites them and `guard` protects them.
[merge]
skip_paths = ["docs/**", "**/*.md"]

[[stream]]
name = "version-bump-bot"
source = { file = "pyproject.toml", format = "toml-path", path = "project.version" }
targets = [
  { file = ".github/workflows/bump.yml", regex = 'VERSION_BUMP_BOT_REF: v(?P<version>\d+\.\d+\.\d+)' },
  { file = ".github/workflows/guard.yml", regex = 'VERSION_BUMP_BOT_REF: v(?P<version>\d+\.\d+\.\d+)' },
]
breaking = "major"
tag = "v{version}"
```

- [ ] **Step 2: Write the self-adoption caller workflow**

`.github/workflows/version.yml`:

```yaml
# This repo adopts its own bot. `uses: ./...` runs the workflows from the
# current commit, and bot_ref points the bot checkout at the same commit, so
# a release run never has to check out the tag it is about to create.
name: Version

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]
  workflow_dispatch:

permissions:
  contents: read

jobs:
  guard:
    if: github.event_name == 'pull_request'
    uses: ./.github/workflows/guard.yml
    with:
      bot_ref: ${{ github.event.pull_request.head.sha }}

  bump:
    if: github.event_name != 'pull_request'
    uses: ./.github/workflows/bump.yml
    with:
      bot_ref: ${{ github.sha }}
    secrets: inherit
```

- [ ] **Step 3: Extend `tests/test_release_tag.py`**

Add `from version_bump.config import load_config` to the import block at the top of the file (after `from pathlib import Path`), then append this test:

```python
def test_self_adoption_config_targets_both_reusable_workflows():
    cfg = load_config(ROOT / ".github" / "version-bump.toml")
    stream = cfg.stream("version-bump-bot")
    assert stream.source.file == "pyproject.toml" and stream.source.path == "project.version"
    assert {t.file for t in stream.targets} == {".github/workflows/bump.yml", ".github/workflows/guard.yml"}
    assert stream.tag == "v{version}"
```

- [ ] **Step 4: Write the local end-to-end test**

`tests/test_e2e.py`:

```python
"""The CLI sequence bump.yml runs, against a local scratch repo. No remote, no push."""

import json

from version_bump import gitops
from version_bump.cli import main

CONFIG = r'''
[merge]
skip_paths = ["docs/**", "**/*.md"]

[[stream]]
name = "server"
source = { file = ".version", format = "json-semver" }
targets = [{ file = "api/version.go", regex = 'Version = "(?P<version>\d+\.\d+\.\d+)"' }]
breaking = "minor"
tag = "v{version}"

[[stream]]
name = "schema"
source = { file = "openapi.json", format = "json-path", path = "info.version" }
trigger = { changed = ["openapi.json"], ignore_json_paths = ["info.version"] }
breaking = "major"
after = ["python3 -c \"import json; open('generated.txt','w').write(json.load(open('openapi.json'))['info']['version'])\""]
verify = ["test \"$(cat generated.txt)\" = \"$(python3 -c 'import json;print(json.load(open(\"openapi.json\"))[\"info\"][\"version\"])')\""]
tag = "schema/v{version}"
'''


def cli(repo, *args, capsys):
    rc = main(["--repo", str(repo.path), *args])
    out = capsys.readouterr()
    return rc, out.out, out.err


def test_full_bump_cycle(repo, capsys):
    repo.write(".github/version-bump.toml", CONFIG)
    repo.write(".version", '{"major": 1, "minor": 8, "patch": 16, "prerelease": ""}\n')
    repo.write("api/version.go", 'package api\n\nconst Version = "1.8.16"\n')
    repo.write("openapi.json", '{"info": {"version": "2.3.1"}, "paths": {"/a": {}}}\n')
    repo.write("generated.txt", "2.3.1")
    repo.commit("chore(version): bump server to 1.8.16, schema to 2.3.1")

    # Three merged PRs: fix, feat with a schema change, docs-only.
    repo.write("main.go", "package main // 1\n")
    repo.commit("fix: one (#2)")
    repo.write("openapi.json", '{"info": {"version": "2.3.1"}, "paths": {"/a": {}, "/b": {}}}\n')
    repo.commit("feat(api): add b (#3)")
    repo.write("docs/notes.md", "n\n")
    repo.commit("docs: notes (#4)")

    # 1. plan
    rc, out, _ = cli(repo, "plan", capsys=capsys)
    assert rc == 0
    plan = json.loads(out)
    assert {s["name"]: s["to"] for s in plan["streams"]} == {"server": "1.9.0", "schema": "2.4.0"}
    assert len(plan["pending"]) == 2
    plan_file = repo.path.parent / "plan.json"
    plan_file.write_text(out)

    # 2. apply, 3. hooks
    assert cli(repo, "apply", "--plan", str(plan_file), capsys=capsys)[0] == 0
    assert cli(repo, "hooks", "--plan", str(plan_file), capsys=capsys)[0] == 0
    assert (repo.path / "generated.txt").read_text() == "2.4.0"

    # 4. re-plan the working tree: nothing pending, tree self-consistent
    rc, out, _ = cli(repo, "plan", "--worktree", capsys=capsys)
    assert rc == 0 and json.loads(out)["streams"] == []

    # 5. commit exactly as the workflow does (git add -u, message from the plan)
    msg = repo.path.parent / "message.txt"
    msg.write_text(plan["commit_subject"] + "\n\n" + plan["commit_body"])
    repo.git("add", "-u")
    repo.git("commit", "-q", "-F", str(msg))
    assert gitops.subject(repo.path, "HEAD") == "chore(version): bump server to 1.9.0, schema to 2.4.0"
    assert "generated.txt" in repo.git("show", "--stat", "--format=", "HEAD")

    # 6. tags: create, then idempotent
    rc, out, _ = cli(repo, "tag", "--plan", str(plan_file), capsys=capsys)
    assert rc == 0 and json.loads(out)["created"] == ["v1.9.0", "schema/v2.4.0"]
    rc, out, _ = cli(repo, "tag", "--plan", str(plan_file), capsys=capsys)
    assert rc == 0 and json.loads(out)["existing"] == ["v1.9.0", "schema/v2.4.0"]
    assert gitops.tag_target(repo.path, "v1.9.0") == gitops.rev_parse(repo.path, "HEAD")

    # 7. no cascade: a run triggered by the bump commit plans nothing
    rc, out, _ = cli(repo, "plan", capsys=capsys)
    assert rc == 0 and json.loads(out)["streams"] == [] and json.loads(out)["pending"] == []

    # 8. guard on a PR branch: clean PR passes, hand bump fails
    base = gitops.rev_parse(repo.path, "HEAD")
    repo.git("checkout", "-q", "-b", "pr")
    repo.write("main.go", "package main // 2\n")
    repo.commit("fix: clean pr")
    assert cli(repo, "guard", "--base", base, capsys=capsys)[0] == 0
    repo.write(".version", '{"major": 2, "minor": 0, "patch": 0, "prerelease": ""}\n')
    repo.commit("fix: hand bump")
    rc, _, err = cli(repo, "guard", "--base", base, capsys=capsys)
    assert rc == 1 and ".version changed 1.9.0 -> 2.0.0" in err


def test_apply_without_hooks_fails_worktree_replan_when_verify_state_is_stale(repo, capsys):
    """A stream whose target disagrees after apply is caught by `plan --worktree`."""
    repo.write(
        ".github/version-bump.toml",
        '[[stream]]\nname = "s"\nsource = { file = "v.json", format = "json-semver" }\n'
        'targets = [{ file = "t.txt", regex = "v=(?P<version>\\\\d+\\\\.\\\\d+\\\\.\\\\d+)" }]\n',
    )
    repo.write("v.json", '{"major": 1, "minor": 0, "patch": 0}')
    repo.write("t.txt", "v=1.0.0\n")
    repo.commit("chore(version): seed")
    repo.write("x", "x")
    repo.commit("fix: x")
    # Simulate a broken apply that only wrote the source.
    repo.write("v.json", '{"major": 1, "minor": 0, "patch": 1}')
    rc, _, err = cli(repo, "plan", "--worktree", capsys=capsys)
    assert rc == 1 and "t.txt has 1.0.0, source has 1.0.1" in err
```

Run: `uv run pytest tests/test_e2e.py tests/test_release_tag.py`
Expected: PASS (all code exists; this task adds config and tests only). If `test_full_bump_cycle` fails at step 5 because `generated.txt` is missing from the commit, check that the `after` hook wrote it (it is a tracked file from the seed commit, so `git add -u` stages it).

- [ ] **Step 5: Write the README (replaces the Task 1 stub)**

`README.md`:

````markdown
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
   commits in the body and pushes it; if the push is rejected because the
   branch moved, it exits 0 (the newer push's run folds everything); any other
   rejection fails, naming the App that must be the ruleset bypass actor;
7. creates and pushes each bumped stream's `tag` (idempotent; a tag on a
   different commit is a hard error; tags never move).

On every pull request, `guard.yml` runs `version-bump guard`: it fails when any
stream's source value or target value differs between the merge base and the
PR head, then runs each stream's `verify` commands. Regenerated files that
merely contain the version never trip it, because it compares values, not
files. The check is named **`guard / Version Guard`** (GitHub names a reusable
workflow's check `<caller job> / <called job>`; keep the caller job id `guard`).

## Adopting a repo

1. **Install the App** `ericfitz-version-bump` on the repo (Contents read/write,
   Metadata read). Set the two secrets locally; values never go into chat or logs:
   `gh secret set VERSION_BUMP_APP_ID` and `gh secret set VERSION_BUMP_APP_PRIVATE_KEY < key.pem`.
   Repos that run Dependabot also need them in the Dependabot secret store
   (`gh secret set --app dependabot ...`).
2. **Add `.github/version-bump.toml`** (see Config).
3. **Add a thin caller workflow**, `.github/workflows/version.yml`:

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

4. **Repo settings:** squash merges only, squash commit title `PR_TITLE`; the App
   is the **only** bypass actor on the default-branch ruleset; `guard / Version
   Guard` is a required check. Verify everything read-only and get the exact
   `gh api` commands for anything missing:

   ```sh
   uv run --project /path/to/version-bump-bot version-bump doctor --app-id <APP_ID>
   ```

5. Commit the version files once by hand (the fold base is the last commit that
   set a source value; a repo with no such commit fails `plan` with a clear error).

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
| `plan [--ref REF] [--worktree]` | read-only; prints the plan JSON (`pending`, `streams`, `base`, `commit_subject`, `commit_body`). `--worktree` treats uncommitted changes as the bump commit and fails if a target disagrees with its source. |
| `apply --plan FILE` | writes the source and targets of each bumped stream; no hooks, no commit. |
| `hooks --plan FILE` | runs each bumped stream's `after` commands. |
| `guard --base SHA [--head REF]` | read-only value comparison, then `verify` commands. |
| `tag --plan FILE [--commit SHA]` | creates the plan's tags locally (idempotent, never moves one); prints `{"created","existing","all"}`. |
| `doctor [--repo-slug O/R] [--app-id N] [--check-name NAME]` | read-only `gh api` checks of merge settings, bypass actor, required check and config; prints fix commands. |

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
The first release is a PR titled `feat!: release version-bump-bot 1.0.0`.
````

- [ ] **Step 6: Run everything**

Run: `actionlint && uv run pytest && uv run ruff check . && uv run ruff format --check .`
Expected: all clean. Confirm `git status` shows only the intended files.

- [ ] **Step 7: Commit**

```bash
git add .github/version-bump.toml .github/workflows/version.yml README.md tests/test_e2e.py tests/test_release_tag.py
git commit -m "feat: adopt version-bump-bot on its own repo and document adoption"
```

---

## Release process (after Task 14; needs Eric for the App and settings)

Order matters: the self-adoption caller workflow runs on every push to `main`, so the App and secrets must exist before the first merge that includes `version.yml`.

1. **Eric, once:** create the GitHub App `ericfitz-version-bump` (Contents read/write, Metadata read, no webhook), install it on `ericfitz/version-bump-bot`, and run locally `gh secret set VERSION_BUMP_APP_ID` and `gh secret set VERSION_BUMP_APP_PRIVATE_KEY < key.pem` in this repo. Never paste the key into chat or a log.
2. **Eric, once:** repo settings per `version-bump doctor --app-id <APP_ID>`: squash-only with `PR_TITLE`, the App as the only bypass actor on the `main` ruleset, `guard / Version Guard` required.
3. **Executor:** open the PR with all tasks and squash-merge it. That squash commit is the one that introduces `pyproject.toml`'s value, so it IS the fold base: the first `Version` run on `main` reports "Nothing to bump." and exits 0. That is correct, not a failure.
4. **Executor:** open the release PR titled `feat!: release version-bump-bot 1.0.0`. It must change something outside `skip_paths` (a `docs/` or `*.md`-only PR bumps nothing), e.g. the module docstring in `src/version_bump/__init__.py`. This is the first real bump. After merge, confirm in the Actions log: the plan JSON, apply, re-plan empty, push, tag push, and that the push-triggered second run of `Version` was **skipped** by the actor guard. Then: `pyproject.toml` is `1.0.0`, both workflows embed `v1.0.0`, tags `v1.0.0` and `v1` exist. Adopters can now pin `@v1`.
5. Hand off to the tmi and tmi-ux agents with the README's adoption checklist.

## Spec ambiguities resolved in this plan (confirm with Eric)

1. **Fold base compares values, not file touches** (spec bump rule 1 vs the prototype's `git log -- .version`): a reformat of a source file is folded as a normal commit; absence or unparsable content at a historical commit counts as a distinct value.
2. **Reusable-workflow check name:** GitHub reports it as `guard / Version Guard`; the README tells adopters to keep the caller job id `guard`, and `doctor` accepts a context equal to `Version Guard` or ending in `/ Version Guard` (its fix adds `guard / Version Guard`).
3. **Self-adoption bootstrap + constant sync:** `bump.yml`/`guard.yml` take a `bot_ref` input (the self-caller passes the current sha so a release never checks out the tag it is creating); the embedded `VERSION_BUMP_BOT_REF` constant is a regex **target** of the self-adoption stream, so `apply` rewrites it and `guard` protects it, with CI double-checking.
4. **Moving `v1` alias vs "tags never move":** the bot's `tag` never moves anything; the alias is force-moved by a separate tag-triggered workflow `release-alias.yml` in this repo only.
5. **Extra CLI subcommands and `setup` grammar:** `hooks` and `tag` are added beyond the spec's four so the workflow's steps 5 and 8 are testable locally; `setup` is a fixed token menu (`go`, `node`, `pnpm`, `uv`) plus `name@version` Go installs with an `oapi-codegen` alias, because a reusable workflow cannot do dynamic `uses:`. Also: regex targets may capture a subset of components (the spec's own example does), `ignore_json_paths` applies only to `.json` files matched by `changed`, `guard` skips a stream whose source is absent at the merge base (the adopting PR), `breaking` defaults to `major`, no `[skip ci]` in the bump commit, and the bot repo is assumed public.
