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
    for key in ("path", "regex"):
        if key in table and not isinstance(table[key], str):
            raise ConfigError(f"{where}: {key} must be a string")
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
    return Trigger(
        changed, _str_list(table.get("ignore_json_paths", []), f"{where}.trigger.ignore_json_paths")
    )


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
    targets = tuple(
        _file_spec(t, f"{where}: targets[{i}]", "target") for i, t in enumerate(raw_targets)
    )
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
            raise ConfigError(
                f"{where}: tag must contain {{version}} (or {{major}}.{{minor}}.{{patch}})"
            )
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
