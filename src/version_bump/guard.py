"""PR guard: version state may only change in the post-merge bump commit (spec: CLI `guard`)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from version_bump import gitops
from version_bump.config import Config
from version_bump.errors import GuardError
from version_bump.formats import FileSpec, read_full, read_partial
from version_bump.shell import run_commands

_SUFFIX = "; only the post-merge bump may write it"


@dataclass
class GuardResult:
    violations: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


def _value_text(repo: Path, ref: str, spec: FileSpec, full: bool) -> str | None:
    text = gitops.show_file(repo, ref, spec.file)
    if text is None:
        return None
    return str(read_full(text, spec)) if full else read_partial(text, spec).text


def check_values(repo: Path, config: Config, base: str, head: str) -> GuardResult:
    base = gitops.rev_parse(repo, base)
    head = gitops.rev_parse(repo, head)
    result = GuardResult()
    for stream in config.streams:
        src_base = _value_text(repo, base, stream.source, full=True)
        if src_base is None:
            result.skipped.append(
                f"{stream.name}: source {stream.source.file} absent at base (new stream); skipped"
            )
            continue
        src_head = _value_text(repo, head, stream.source, full=True)
        if src_head != src_base:
            shown = "<absent>" if src_head is None else src_head
            result.violations.append(
                f"{stream.name}: {stream.source.file} changed {src_base} -> {shown}{_SUFFIX}"
            )
        for target in stream.targets:
            t_base = _value_text(repo, base, target, full=False)
            if t_base is None:
                result.skipped.append(
                    f"{stream.name}: target {target.file} absent at base; skipped"
                )
                continue
            t_head = _value_text(repo, head, target, full=False)
            if t_head != t_base:
                shown = "<absent>" if t_head is None else t_head
                result.violations.append(
                    f"{stream.name}: {target.file} changed {t_base} -> {shown}{_SUFFIX}"
                )
    return result


def run_verify(repo: Path, config: Config) -> list[str]:
    ran: list[str] = []
    for stream in config.streams:
        ran += run_commands(repo, stream.verify, stream=stream.name, kind="verify command")
    return ran


def guard(repo: Path, config: Config, base: str, head: str = "HEAD") -> GuardResult:
    result = check_values(repo, config, base, head)
    if result.violations:
        raise GuardError("\n".join(result.violations))
    run_verify(repo, config)
    return result
