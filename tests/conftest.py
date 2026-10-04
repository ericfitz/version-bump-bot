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
