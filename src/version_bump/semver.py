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

FEAT_RE = re.compile(r"^feat(\([^)]*\))?!?:")
BREAKING_RE = re.compile(r"^[a-z]+(\([^)]*\))?!:")


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
