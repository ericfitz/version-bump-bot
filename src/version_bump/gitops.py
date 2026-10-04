"""Thin git wrappers. Every call: stdin=DEVNULL, UTF-8. The runtime honours the user's global and
system git config (e.g. safe.directory); test isolation comes from the fixture."""

from __future__ import annotations

import os
import subprocess
from collections.abc import Sequence
from pathlib import Path

from version_bump.errors import GitError

_ENV_OVERRIDES = {"LC_ALL": "C.UTF-8"}
EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"


def _run(repo: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        env={**os.environ, **_ENV_OVERRIDES},
        stdin=subprocess.DEVNULL,
        capture_output=True,
        check=False,
    )


def _decode(data: bytes) -> str:
    return data.decode("utf-8", "surrogateescape")


def git(repo: Path, *args: str, check: bool = True) -> str:
    proc = _run(repo, *args)
    if check and proc.returncode != 0:
        stderr = _decode(proc.stderr).strip()
        raise GitError(f"git {' '.join(args)} failed ({proc.returncode}): {stderr}")
    return _decode(proc.stdout).strip()


def rev_parse(repo: Path, ref: str) -> str:
    return git(repo, "rev-parse", "--verify", f"{ref}^{{commit}}")


def parent(repo: Path, sha: str) -> str | None:
    out = git(repo, "rev-parse", "--verify", "-q", f"{sha}^1", check=False)
    return out or None


def show_file(repo: Path, ref: str, path: str) -> str | None:
    proc = _run(repo, "show", f"{ref}:{path}")
    if proc.returncode != 0:
        return None
    return _decode(proc.stdout)  # NOT stripped, no newline translation: file bytes matter


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
