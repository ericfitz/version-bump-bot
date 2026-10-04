"""Read-only check of an adopting repo's settings, with the exact fix commands (spec: CLI `doctor`)."""

from __future__ import annotations

import copy
import json
import os
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from version_bump import gitops
from version_bump.config import load_config
from version_bump.errors import VersionBumpError
from version_bump.lockfiles import discover, worktree_reader

Fetch = Callable[[str], Any]
_SLUG_RE = re.compile(r"github\.com[:/]([^/]+)/([^/]+?)(?:\.git)?/?$")
_STRIP_KEYS = (
    "id",
    "node_id",
    "_links",
    "created_at",
    "updated_at",
    "source",
    "source_type",
    "current_user_can_bypass",
)


@dataclass
class Finding:
    ok: bool
    check: str
    detail: str
    fix: str | None = None


def gh_fetch(path: str) -> Any:
    proc = subprocess.run(
        ["gh", "api", path],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise VersionBumpError(f"gh api {path} failed: {proc.stderr.strip()}")
    return json.loads(proc.stdout)


def detect_repo_slug(repo: Path) -> str | None:
    env = os.environ.get("GITHUB_REPOSITORY")
    if env:
        return env
    url = gitops.git(repo, "config", "--get", "remote.origin.url", check=False)
    m = _SLUG_RE.search(url)
    return f"{m.group(1)}/{m.group(2)}" if m else None


def _heredoc(method: str, path: str, body: dict[str, Any]) -> str:
    return f"gh api -X {method} {path} --input - <<'JSON'\n{json.dumps(body, indent=2)}\nJSON"


def _check_merge_settings(slug: str, repo: dict[str, Any]) -> Finding:
    want = {
        "allow_squash_merge": True,
        "allow_merge_commit": False,
        "allow_rebase_merge": False,
        "squash_merge_commit_title": "PR_TITLE",
    }
    wrong = {k: repo.get(k) for k, v in want.items() if repo.get(k) != v}
    fix = (
        f"gh api -X PATCH repos/{slug} -F allow_squash_merge=true -F allow_merge_commit=false "
        "-F allow_rebase_merge=false -f squash_merge_commit_title=PR_TITLE "
        "-f squash_merge_commit_message=PR_BODY"
    )
    if wrong:
        return Finding(
            False, "merge settings", f"not squash-only with PR_TITLE subjects: {wrong}", fix
        )
    return Finding(True, "merge settings", "squash-only merges with PR_TITLE subjects")


def _default_branch_rulesets(slug: str, default_branch: str, fetch: Fetch) -> list[dict[str, Any]]:
    out = []
    for item in fetch(f"repos/{slug}/rulesets?targets=branch"):
        rs = fetch(f"repos/{slug}/rulesets/{item['id']}")
        if rs.get("enforcement") != "active":
            continue
        include = rs.get("conditions", {}).get("ref_name", {}).get("include", [])
        if "~DEFAULT_BRANCH" in include or f"refs/heads/{default_branch}" in include:
            out.append(rs)
    return out


def _check_contexts(rulesets: list[dict[str, Any]]) -> list[str]:
    ctx = []
    for rs in rulesets:
        for rule in rs.get("rules", []):
            if rule.get("type") == "required_status_checks":
                ctx += [c["context"] for c in rule["parameters"].get("required_status_checks", [])]
    return ctx


def _matches_check(context: str, check_name: str) -> bool:
    return context == check_name or context.endswith(" / " + check_name)


def _app_actor(app_id: int | None, existing: list[dict[str, Any]]) -> dict[str, Any]:
    """The App bypass actor. Without --app-id keep an existing Integration actor's id; only when
    there is none does the actor_id 0 placeholder appear (callers say so in the finding)."""
    if app_id is None:
        known = [a for a in existing if a.get("actor_type") == "Integration"]
        actor_id = known[0]["actor_id"] if known else 0
    else:
        actor_id = app_id
    return {
        "actor_id": actor_id,
        "actor_type": "Integration",
        "bypass_mode": "always",
    }


def _fixed_ruleset(
    rs: dict[str, Any], app_id: int | None, check_name: str, check_context: str
) -> dict[str, Any]:
    fixed = copy.deepcopy(rs)
    for k in _STRIP_KEYS:
        fixed.pop(k, None)
    fixed["bypass_actors"] = [_app_actor(app_id, rs.get("bypass_actors", []))]
    rules = [r for r in fixed.get("rules", []) if r.get("type") != "required_status_checks"]
    existing = [r for r in fixed.get("rules", []) if r.get("type") == "required_status_checks"]
    checks = existing[0]["parameters"].get("required_status_checks", []) if existing else []
    if not any(_matches_check(c["context"], check_name) for c in checks):
        checks = [*checks, {"context": check_context}]
    rules.append(
        {
            "type": "required_status_checks",
            "parameters": {
                "strict_required_status_checks_policy": False,
                "required_status_checks": checks,
            },
        }
    )
    fixed["rules"] = rules
    return fixed


def _new_ruleset(app_id: int | None, check_context: str) -> dict[str, Any]:
    return {
        "name": "default-branch",
        "target": "branch",
        "enforcement": "active",
        "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
        "bypass_actors": [_app_actor(app_id, [])],
        "rules": [
            {"type": "deletion"},
            {"type": "non_fast_forward"},
            {
                "type": "pull_request",
                "parameters": {
                    "required_approving_review_count": 0,
                    "dismiss_stale_reviews_on_push": False,
                    "require_code_owner_review": False,
                    "require_last_push_approval": False,
                    "required_review_thread_resolution": False,
                },
            },
            {
                "type": "required_status_checks",
                "parameters": {
                    "strict_required_status_checks_policy": False,
                    "required_status_checks": [{"context": check_context}],
                },
            },
        ],
    }


def run_doctor(
    repo_slug: str,
    config_path: Path,
    fetch: Fetch,
    app_id: int | None,
    check_name: str = "Version Guard",
    repo_dir: Path | None = None,
) -> list[Finding]:
    findings: list[Finding] = []
    try:
        config = load_config(config_path)
        findings.append(Finding(True, "config", f"{config_path} is valid"))
    except VersionBumpError as exc:
        config = None
        findings.append(Finding(False, "config", str(exc), str(exc)))
    if config is not None and repo_dir is not None:
        locks = discover(config, worktree_reader(repo_dir))
        for e in locks.entries:
            detail = f"{e.file}: entry {e.name!r} follows {e.manifest.file} ({e.stream})"
            findings.append(Finding(True, "lockfile", detail))
        for w in locks.warnings:
            findings.append(Finding(True, "lockfile", f"skipped: {w}"))

    repo = fetch(f"repos/{repo_slug}")
    findings.append(_check_merge_settings(repo_slug, repo))

    default_branch = repo.get("default_branch", "main")
    rulesets = _default_branch_rulesets(repo_slug, default_branch, fetch)
    check_context = f"guard / {check_name}"
    placeholder = " (the fix uses actor_id 0 as a placeholder: pass --app-id)"
    if not rulesets:
        note = placeholder if app_id is None else ""
        fix = _heredoc("POST", f"repos/{repo_slug}/rulesets", _new_ruleset(app_id, check_context))
        findings.append(
            Finding(False, "bypass actor", f"no active ruleset targets {default_branch}{note}", fix)
        )
        findings.append(
            Finding(False, "required check", f"no ruleset requires {check_name!r}", fix)
        )
        return findings

    actors = [a for rs in rulesets for a in rs.get("bypass_actors", [])]
    note = (
        placeholder
        if app_id is None and not any(a.get("actor_type") == "Integration" for a in actors)
        else ""
    )
    fix = _heredoc(
        "PUT",
        f"repos/{repo_slug}/rulesets/{rulesets[0]['id']}",
        _fixed_ruleset(rulesets[0], app_id, check_name, check_context),
    )
    one_integration = (
        len(actors) == 1
        and actors[0].get("actor_type") == "Integration"
        and actors[0].get("bypass_mode") == "always"
    )
    if not one_integration:
        findings.append(
            Finding(
                False,
                "bypass actor",
                f"expected exactly one Integration bypass actor (the App), found {actors}{note}",
                fix,
            )
        )
    elif app_id is None:
        findings.append(
            Finding(
                True,
                "bypass actor",
                f"one Integration actor {actors[0]['actor_id']}; "
                "pass --app-id to verify it is the App",
            )
        )
    elif actors[0].get("actor_id") != app_id:
        findings.append(
            Finding(
                False,
                "bypass actor",
                f"bypass actor is {actors[0]['actor_id']}, expected App {app_id}",
                fix,
            )
        )
    else:
        findings.append(Finding(True, "bypass actor", f"App {app_id} is the only bypass actor"))

    contexts = _check_contexts(rulesets)
    if any(_matches_check(c, check_name) for c in contexts):
        findings.append(Finding(True, "required check", f"{check_name!r} is required"))
    else:
        findings.append(
            Finding(
                False,
                "required check",
                f"{check_name!r} is not a required check (found {contexts}){note}",
                fix,
            )
        )
    return findings


def format_report(findings: list[Finding]) -> str:
    lines = []
    for f in findings:
        lines.append(f"{'OK  ' if f.ok else 'FAIL'} {f.check}: {f.detail}")
        if not f.ok and f.fix:
            if "\n" in f.fix:  # heredoc: body and terminator must stay at column 0
                lines.append("  fix:")
                lines.append(f.fix)
            else:
                lines.append("  fix: " + f.fix)
    return "\n".join(lines)
