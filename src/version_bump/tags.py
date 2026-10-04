"""Release tags: created once at the bump commit, idempotent, never moved."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from version_bump import gitops
from version_bump.errors import TagError
from version_bump.plan import Plan


@dataclass
class TagOutcome:
    created: list[str] = field(default_factory=list)
    existing: list[str] = field(default_factory=list)

    @property
    def all(self) -> list[str]:
        return self.created + self.existing


def plan_tags(plan: Plan) -> list[str]:
    return [s.tag for s in plan.streams if s.tag]


def ensure_tags(repo: Path, tags: list[str], sha: str) -> TagOutcome:
    sha = gitops.rev_parse(repo, sha)
    outcome = TagOutcome()
    todo: list[str] = []
    for tag in dict.fromkeys(tags):
        at = gitops.tag_target(repo, tag)
        if at is None:
            todo.append(tag)
        elif at == sha:
            outcome.existing.append(tag)
        else:
            raise TagError(f"tag {tag} already exists at {at[:7]}, not {sha[:7]}; tags never move")
    for tag in todo:
        gitops.create_tag(repo, tag, sha)
        outcome.created.append(tag)
    return outcome
