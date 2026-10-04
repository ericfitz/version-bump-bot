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
