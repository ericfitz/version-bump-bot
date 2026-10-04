"""Lockfiles that record the project's own version: find that entry and keep it in sync
(spec: 2026-10-03-lockfile-sync-design.md)."""

from __future__ import annotations

import json
import posixpath
import re
import tomllib
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from version_bump import gitops
from version_bump.config import Config
from version_bump.errors import FormatError, VersionBumpError
from version_bump.formats import FileSpec
from version_bump.jsonpos import locate_json_keys
from version_bump.semver import Version


@dataclass(frozen=True)
class LockEntry:
    stream: str
    manifest: FileSpec
    file: str
    kind: str  # "uv" | "cargo" | "npm"
    name: str
    member: str  # npm: manifest dir relative to the lockfile dir ("" = same dir); else ""


# --- uv.lock / Cargo.lock: [[package]] tables -----------------------------------
_PKG_HEADER = re.compile(r"^\s*\[\[\s*package\s*\]\]\s*(?:#.*)?$")
_ANY_HEADER = re.compile(r"^\s*\[")
_VERSION_LINE = re.compile(r'^(\s*version\s*=\s*")(\d+\.\d+\.\d+)(")')


def _pep503(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _is_own(entry: LockEntry, pkg: dict[str, Any]) -> bool:
    name = pkg.get("name")
    if not isinstance(name, str):
        return False
    if entry.kind == "uv":
        source = pkg.get("source")
        return (
            _pep503(name) == _pep503(entry.name)
            and isinstance(source, dict)
            and ("editable" in source or "virtual" in source)
        )
    return name == entry.name and "source" not in pkg


def _toml_index(entry: LockEntry, text: str) -> tuple[int, Version]:
    where = entry.file
    try:
        obj = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise FormatError(f"{where}: invalid TOML: {exc}") from None
    pkgs = obj.get("package")
    if not isinstance(pkgs, list):
        raise FormatError(f"{where}: no [[package]] entries")
    hits = [i for i, p in enumerate(pkgs) if isinstance(p, dict) and _is_own(entry, p)]
    if len(hits) != 1:
        raise FormatError(
            f"{where}: expected exactly one [[package]] entry for {entry.name!r}, found {len(hits)}"
        )
    raw = pkgs[hits[0]].get("version")
    if not isinstance(raw, str):
        raise FormatError(f"{where}: entry for {entry.name!r} has no version")
    return hits[0], Version.parse(raw)


def _toml_write(entry: LockEntry, text: str, v: Version) -> str:
    index, _ = _toml_index(entry, text)
    lines = text.splitlines(keepends=True)
    headers = [i for i, line in enumerate(lines) if _PKG_HEADER.match(line)]
    if len(headers) <= index:
        raise FormatError(f"{entry.file}: [[package]] tables are not in header form")
    start = headers[index] + 1
    end = next((i for i in range(start, len(lines)) if _ANY_HEADER.match(lines[i])), len(lines))
    hits = [i for i in range(start, end) if _VERSION_LINE.match(lines[i])]
    if len(hits) != 1:
        raise FormatError(
            f"{entry.file}: expected one 'version = \"X.Y.Z\"' line for {entry.name!r}, "
            f"found {len(hits)}"
        )
    i = hits[0]
    lines[i] = _VERSION_LINE.sub(lambda m: m.group(1) + str(v) + m.group(3), lines[i], count=1)
    return "".join(lines)


# --- package-lock.json / npm-shrinkwrap.json --------------------------------------
def _npm_keys(entry: LockEntry, text: str) -> tuple[list[list[str]], Version]:
    where = entry.file
    try:
        obj = json.loads(text)
    except json.JSONDecodeError as exc:
        raise FormatError(f"{where}: invalid JSON: {exc.msg} at line {exc.lineno}") from None
    if not isinstance(obj, dict) or obj.get("lockfileVersion") not in (2, 3):
        raise FormatError(f"{where}: unsupported lockfileVersion (need 2 or 3)")
    packages = obj.get("packages")
    pkg = packages.get(entry.member) if isinstance(packages, dict) else None
    if not isinstance(pkg, dict) or not isinstance(pkg.get("version"), str):
        raise FormatError(
            f"{where}: expected exactly one packages[{entry.member!r}] with a version"
        )
    if "name" in pkg and pkg["name"] != entry.name:
        raise FormatError(
            f"{where}: packages[{entry.member!r}] has name {pkg['name']!r}, "
            f"manifest has {entry.name!r}"
        )
    keys = [["packages", entry.member, "version"]]
    if entry.member == "" and isinstance(obj.get("version"), str):
        keys.append(["version"])
    return keys, Version.parse(pkg["version"])


def _npm_write(entry: LockEntry, text: str, v: Version) -> str:
    keys, _ = _npm_keys(entry, text)
    spans = sorted((locate_json_keys(text, k) for k in keys), reverse=True)
    for s, e in spans:
        if not re.fullmatch(r'"\d+\.\d+\.\d+"', text[s:e]):
            raise FormatError(f"{entry.file}: version {text[s:e]} is not plain X.Y.Z")
        text = text[: s + 1] + str(v) + text[e - 1 :]
    return text


# --- public ------------------------------------------------------------------------
def read_entry(text: str, entry: LockEntry) -> Version:
    if entry.kind == "npm":
        return _npm_keys(entry, text)[1]
    return _toml_index(entry, text)[1]


def write_entry(text: str, entry: LockEntry, v: Version) -> str:
    if entry.kind == "npm":
        return _npm_write(entry, text, v)
    return _toml_write(entry, text, v)


Reader = Callable[[str], "str | None"]


def worktree_reader(repo: Path) -> Reader:
    def read(rel: str) -> str | None:
        p = repo / rel
        return p.read_bytes().decode("utf-8", "surrogateescape") if p.is_file() else None

    return read


def tracked_reader(repo: Path) -> Reader:
    """Working-tree text, but only for files tracked at HEAD: the bump commits with `git add -u`,
    so an untracked or ignored lockfile must never be written or checked."""
    worktree = worktree_reader(repo)
    return lambda rel: worktree(rel) if gitops.show_file(repo, "HEAD", rel) is not None else None


def ref_reader(repo: Path, ref: str) -> Reader:
    return lambda rel: gitops.show_file(repo, ref, rel)


@dataclass(frozen=True)
class _Manifest:
    format: str
    path: str
    name_keys: tuple[str, ...]
    lockfiles: tuple[str, ...]  # per directory, in preference order
    kind: str


_MANIFESTS = {
    "pyproject.toml": _Manifest(
        "toml-path", "project.version", ("project", "name"), ("uv.lock",), "uv"
    ),
    "package.json": _Manifest(
        "json-path", "version", ("name",), ("npm-shrinkwrap.json", "package-lock.json"), "npm"
    ),
    "Cargo.toml": _Manifest(
        "toml-path", "package.version", ("package", "name"), ("Cargo.lock",), "cargo"
    ),
}


@dataclass
class Discovery:
    entries: list[LockEntry] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def for_stream(self, name: str) -> list[LockEntry]:
        return [e for e in self.entries if e.stream == name]


def _manifest_kind(spec: FileSpec) -> _Manifest | None:
    m = _MANIFESTS.get(posixpath.basename(spec.file))
    if m is not None and spec.format == m.format and spec.path == m.path:
        return m
    return None


def _project_name(where: str, text: str, m: _Manifest) -> str:
    try:
        obj: Any = json.loads(text) if m.kind == "npm" else tomllib.loads(text)
    except (json.JSONDecodeError, tomllib.TOMLDecodeError) as exc:
        raise FormatError(f"{where}: cannot parse: {exc}") from None
    for key in m.name_keys:
        obj = obj.get(key) if isinstance(obj, dict) else None
    if not isinstance(obj, str) or not obj:
        raise FormatError(f"{where}: no {'.'.join(m.name_keys)} to identify the lockfile entry")
    return obj


def _find_lockfile(read: Reader, manifest_file: str, m: _Manifest) -> str | None:
    d = posixpath.dirname(manifest_file)
    while True:
        for name in m.lockfiles:
            rel = posixpath.join(d, name) if d else name
            if read(rel) is not None:
                return rel
        if not d:
            return None
        d = posixpath.dirname(d)


def discover(config: Config, read: Reader) -> Discovery:
    found = Discovery()
    owner: dict[tuple[str, str, str], str] = {}
    for stream in config.streams:
        for spec in (stream.source, *stream.targets):
            m = _manifest_kind(spec)
            if m is None:
                continue
            text = read(spec.file)
            lock = _find_lockfile(read, spec.file, m) if text is not None else None
            if text is None or lock is None:
                continue
            try:
                name = _project_name(spec.file, text, m)
                member = ""
                if m.kind == "npm":
                    rel = posixpath.relpath(
                        posixpath.dirname(spec.file) or ".", posixpath.dirname(lock) or "."
                    )
                    member = "" if rel == "." else rel
                entry = LockEntry(stream.name, spec, lock, m.kind, name, member)
                read_entry(read(lock) or "", entry)
            except VersionBumpError as exc:
                found.warnings.append(f"{stream.name}: {lock} not synced: {exc}")
                continue
            key = (entry.file, entry.name, entry.member)
            if key in owner:
                if owner[key] != stream.name:
                    found.warnings.append(
                        f"{stream.name}: {lock} entry {name!r} is already synced by "
                        f"stream {owner[key]!r}; not synced again"
                    )
                continue
            owner[key] = stream.name
            found.entries.append(entry)
    return found
