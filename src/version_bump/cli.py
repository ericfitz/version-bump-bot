"""Command-line entry point: version-bump <subcommand>."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from version_bump import __version__
from version_bump.apply import apply_plan, run_hooks
from version_bump.config import DEFAULT_CONFIG_PATH, Config, load_config
from version_bump.doctor import detect_repo_slug, format_report, gh_fetch, run_doctor
from version_bump.errors import VersionBumpError
from version_bump.guard import guard
from version_bump.plan import Plan, compute_plan
from version_bump.tags import ensure_tags, plan_tags


def _repo_and_config(args: argparse.Namespace) -> tuple[Path, Config]:
    repo = Path(args.repo).resolve()
    return repo, load_config(repo / args.config)


def cmd_plan(args: argparse.Namespace) -> int:
    repo, config = _repo_and_config(args)
    plan = compute_plan(repo, config, ref=args.ref, worktree=args.worktree)
    sys.stdout.write(plan.to_json())
    return 0


def _load_plan(path: str) -> Plan:
    text = sys.stdin.read() if path == "-" else Path(path).read_text(encoding="utf-8")
    return Plan.from_json(text)


def cmd_apply(args: argparse.Namespace) -> int:
    repo, config = _repo_and_config(args)
    for rel in apply_plan(repo, config, _load_plan(args.plan)):
        print(rel)
    return 0


def cmd_hooks(args: argparse.Namespace) -> int:
    run_hooks(Path(args.repo).resolve(), _load_plan(args.plan))
    return 0


def cmd_guard(args: argparse.Namespace) -> int:
    repo, config = _repo_and_config(args)
    result = guard(repo, config, args.base, args.head)
    checked = len(config.streams) - sum(1 for s in result.skipped if "(new stream)" in s)
    print(f"OK: version state untouched ({checked} stream(s) checked)")
    for note in result.skipped:
        print(f"note: {note}")
    return 0


def cmd_tag(args: argparse.Namespace) -> int:
    repo, _ = _repo_and_config(args)
    outcome = ensure_tags(repo, plan_tags(_load_plan(args.plan)), args.commit)
    print(
        json.dumps({"created": outcome.created, "existing": outcome.existing, "all": outcome.all})
    )
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    # run_doctor loads the config itself so an invalid one becomes a finding, not an exception
    repo = Path(args.repo).resolve()
    slug = args.repo_slug or detect_repo_slug(repo)
    if not slug:
        raise VersionBumpError("cannot determine OWNER/REPO; pass --repo-slug")
    app_id = args.app_id if args.app_id is not None else os.environ.get("VERSION_BUMP_APP_ID")
    try:
        app_id_num = int(app_id) if app_id else None
    except ValueError:
        raise VersionBumpError(f"app id must be an integer, got {app_id!r}") from None
    findings = run_doctor(slug, repo / args.config, gh_fetch, app_id_num, args.check_name)
    print(format_report(findings))
    return 0 if all(f.ok for f in findings) else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="version-bump")
    parser.add_argument("--version", action="version", version=f"version-bump {__version__}")
    parser.add_argument("--repo", default=".", help="repository root (default: cwd)")
    parser.add_argument(
        "--config", default=DEFAULT_CONFIG_PATH, help="config path relative to --repo"
    )
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    p = sub.add_parser("plan", help="compute the pending bump (read-only); prints JSON")
    p.add_argument("--ref", default="HEAD")
    p.add_argument(
        "--worktree", action="store_true", help="read current values from the working tree"
    )
    p.set_defaults(func=cmd_plan)

    p = sub.add_parser("apply", help="write source and target files for each bumped stream")
    p.add_argument("--plan", required=True, help="plan JSON file, or - for stdin")
    p.set_defaults(func=cmd_apply)

    p = sub.add_parser("hooks", help="run each bumped stream's `after` commands")
    p.add_argument("--plan", required=True, help="plan JSON file, or - for stdin")
    p.set_defaults(func=cmd_hooks)

    p = sub.add_parser("guard", help="fail if a PR changed version state; then run verify commands")
    p.add_argument("--base", required=True, help="merge-base commit with the default branch")
    p.add_argument("--head", default="HEAD")
    p.set_defaults(func=cmd_guard)

    p = sub.add_parser(
        "tag", help="create the plan's release tags locally (idempotent; never moves a tag)"
    )
    p.add_argument("--plan", required=True, help="plan JSON file, or - for stdin")
    p.add_argument("--commit", default="HEAD", help="commit to tag (default HEAD)")
    p.set_defaults(func=cmd_tag)

    p = sub.add_parser(
        "doctor", help="check repo settings read-only via gh api; print fix commands"
    )
    p.add_argument("--repo-slug", help="OWNER/REPO (default: $GITHUB_REPOSITORY or the origin URL)")
    p.add_argument("--app-id", type=int, help="GitHub App id expected as the ruleset bypass actor")
    p.add_argument("--check-name", default="Version Guard")
    p.set_defaults(func=cmd_doctor)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 2
    try:
        return args.func(args)
    except VersionBumpError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
