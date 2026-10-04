"""Run user-configured shell commands (after hooks, verify commands) with loud failure."""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

from version_bump.errors import HookError


def run_commands(repo: Path, cmds: Sequence[str], *, stream: str, kind: str) -> list[str]:
    """Run each command in order via the shell in repo; stop at the first failure.

    Echoes `+ <cmd>` to stderr, closes stdin, inherits stdout/stderr. Returns the commands run.
    """
    ran: list[str] = []
    for cmd in cmds:
        print(f"+ {cmd}", file=sys.stderr, flush=True)
        proc = subprocess.run(cmd, shell=True, cwd=repo, stdin=subprocess.DEVNULL, check=False)
        if proc.returncode != 0:
            raise HookError(f"stream {stream!r}: {kind} failed (exit {proc.returncode}): {cmd}")
        ran.append(cmd)
    return ran
