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
        return ".".join(
            "?" if getattr(self, c) is None else str(getattr(self, c)) for c in _COMPONENTS
        )

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
        try:
            split_path(spec.path)
        except FormatError:
            raise ConfigError(f"{where}: invalid path {spec.path!r}") from None
    if spec.format == "regex":
        if not spec.regex:
            raise ConfigError(f"{where}: format regex requires 'regex'")
        groups = _regex_groups(spec.regex)
        known = groups & ({"version"} | set(_COMPONENTS))
        if not known:
            raise ConfigError(f"{where}: regex needs a named group 'version' or major/minor/patch")
        if "version" in groups and groups & set(_COMPONENTS):
            raise ConfigError(
                f"{where}: regex uses either 'version' or major/minor/patch, not both"
            )
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
    raw = text[s:e]
    m = VERSION_PREFIX_RE.match(raw[1:])
    if not raw.startswith('"') or not m:
        raise FormatError(f"{where}: cannot locate MAJOR.MINOR.PATCH in raw JSON string {raw!r}")
    return text[: s + 1] + str(v) + text[s + 1 + m.end() :]


# --- toml-path -----------------------------------------------------------------
_TOML_HEADER = re.compile(r"^\s*\[\[?\s*([^\]]+?)\s*\]\]?\s*(?:#.*)?$")


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
        pm = VERSION_PREFIX_RE.match(m.group("version"))
        if not pm:
            raise FormatError(
                f"{where}: {m.group('version')!r} does not start with MAJOR.MINOR.PATCH"
            )
        repl.append((m.start("version"), m.start("version") + pm.end(), str(v)))
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
