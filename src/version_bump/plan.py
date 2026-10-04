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
from version_bump.lockfiles import discover, read_entry, ref_reader, worktree_reader
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
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ref": self.ref,
            "base": self.base,
            "pending": [asdict(c) for c in self.pending],
            "streams": [s.to_dict() for s in self.streams],
            "commit_subject": self.commit_subject,
            "commit_body": self.commit_body,
            "warnings": list(self.warnings),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False) + "\n"

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Plan:
        return cls(
            ref=d["ref"],
            base=d["base"],
            pending=[
                PendingCommit(c["commit"], c["subject"], list(c["streams"])) for c in d["pending"]
            ],
            streams=[StreamPlan.from_dict(s) for s in d["streams"]],
            commit_subject=d["commit_subject"],
            commit_body=d["commit_body"],
            warnings=list(d.get("warnings", [])),
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


def _read_text(p: Path) -> str:
    return p.read_bytes().decode("utf-8", "surrogateescape")


def _worktree_value(repo: Path, stream: Stream) -> Version:
    p = repo / stream.source.file
    if not p.is_file():
        raise ConfigError(
            f"stream {stream.name!r}: source file {stream.source.file} not found in the working tree"
        )
    try:
        return read_full(_read_text(p), stream.source)
    except VersionBumpError as exc:
        raise ConfigError(
            f"stream {stream.name!r}: cannot read {stream.source.file} in the working tree: {exc}"
        ) from None


def _current_value(repo: Path, stream: Stream, ref: str) -> Version:
    text = gitops.show_file(repo, ref, stream.source.file)
    if text is None:
        raise ConfigError(
            f"stream {stream.name!r}: source file {stream.source.file} not found at {ref}"
        )
    try:
        return read_full(text, stream.source)
    except VersionBumpError as exc:
        raise ConfigError(
            f"stream {stream.name!r}: cannot read {stream.source.file} at {ref}: {exc}"
        ) from None


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
    locks = discover(config, worktree_reader(repo))
    for stream in config.streams:
        src = _worktree_value(repo, stream)
        for t in stream.targets:
            p = repo / t.file
            if not p.is_file():
                bad.append(f"{stream.name}: target {t.file} missing")
                continue
            got = read_partial(_read_text(p), t)
            if not got.matches(src):
                bad.append(f"{stream.name}: target {t.file} has {got.text}, source has {src}")
        for e in locks.for_stream(stream.name):
            got_lock = read_entry(_read_text(repo / e.file), e)
            if got_lock != src:
                bad.append(
                    f"{stream.name}: lockfile {e.file} has {e.name} {got_lock}, source has {src}"
                )
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
    locks = discover(config, ref_reader(repo, ref_sha))
    if worktree:
        _check_worktree_consistency(repo, config)
        tree = {s.name: _worktree_value(repo, s) for s in config.streams}
        if any(tree[n] != current[n] for n in current):
            return Plan(
                ref=ref_sha,
                base=WORKTREE,
                pending=[],
                streams=[],
                commit_subject="",
                commit_body="",
                warnings=list(locks.warnings),
            )
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
            files=list(
                dict.fromkeys(
                    [s.source.file]
                    + [t.file for t in s.targets]
                    + [e.file for e in locks.for_stream(s.name)]
                )
            ),
        )
        for s in config.streams
        if s.name in bumped
    ]
    subject, body = _message(streams, pending)
    return Plan(
        ref=ref_sha,
        base=base,
        pending=pending,
        streams=streams,
        commit_subject=subject,
        commit_body=body,
        warnings=list(locks.warnings),
    )
