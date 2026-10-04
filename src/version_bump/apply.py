"""Write the planned versions (source first, then targets) and run `after` hooks."""

from __future__ import annotations

from pathlib import Path

from version_bump import gitops
from version_bump.config import Config
from version_bump.errors import VersionBumpError
from version_bump.formats import FileSpec, read_full, write_version
from version_bump.plan import Plan
from version_bump.semver import Version
from version_bump.shell import run_commands


def _read(repo: Path, rel: str) -> str:
    p = repo / rel
    if not p.is_file():
        raise VersionBumpError(f"cannot apply: {rel} is not in the working tree")
    # Bytes in, bytes out: no newline translation, so CRLF survives.
    return p.read_bytes().decode("utf-8", "surrogateescape")


def _write(repo: Path, rel: str, text: str) -> None:
    (repo / rel).write_bytes(text.encode("utf-8", "surrogateescape"))


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
        raise VersionBumpError(
            f"stale plan: computed at {plan.ref[:7]} but HEAD is {head[:7]}; re-run plan"
        )
    # Pre-check every file so a missing one cannot leave a partial write behind.
    for sp in plan.streams:
        for rel in sp.files:
            if not (repo / rel).is_file():
                raise VersionBumpError(
                    f"stream {sp.name!r}: cannot apply: {rel} is not in the working tree"
                )
    written: list[str] = []
    for sp in plan.streams:
        stream = config.stream(sp.name)
        to = Version.parse(sp.to_version)
        _apply_spec(repo, stream.source, to, written)
        for target in stream.targets:
            _apply_spec(repo, target, to, written)
        got = read_full(_read(repo, stream.source.file), stream.source)
        if got != to:
            raise VersionBumpError(
                f"stream {sp.name!r}: wrote {to} to {stream.source.file} but read back {got}"
            )
    return written


def run_hooks(repo: Path, plan: Plan) -> list[str]:
    ran: list[str] = []
    for sp in plan.streams:
        ran += run_commands(repo, sp.after, stream=sp.name, kind="after hook")
    return ran
