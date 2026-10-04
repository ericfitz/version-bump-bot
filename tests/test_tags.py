import json

import pytest

from version_bump import gitops
from version_bump.errors import TagError
from version_bump.plan import Plan, StreamPlan
from version_bump.tags import ensure_tags, plan_tags


def fake_plan(sha, *tags):
    return Plan(
        ref=sha,
        base=sha,
        pending=[],
        streams=[StreamPlan(f"s{i}", "1.0.0", "1.0.1", t, [], []) for i, t in enumerate(tags)],
        commit_subject="chore(version): bump",
        commit_body="",
    )


def test_plan_tags_skips_null(repo):
    assert plan_tags(fake_plan("x", "v1.0.1", None, "lib/v1.0.1")) == ["v1.0.1", "lib/v1.0.1"]


def test_create_then_idempotent(repo):
    repo.write("a", "0")
    sha = repo.commit("chore: base")
    out = ensure_tags(repo.path, ["v1.0.1", "lib/v1.0.1"], sha)
    assert out.created == ["v1.0.1", "lib/v1.0.1"] and out.existing == []
    again = ensure_tags(repo.path, ["v1.0.1", "lib/v1.0.1"], sha)
    assert again.created == [] and again.existing == ["v1.0.1", "lib/v1.0.1"]
    assert gitops.tag_target(repo.path, "v1.0.1") == sha


def test_conflicting_tag_is_error_and_creates_nothing(repo):
    repo.write("a", "0")
    old = repo.commit("chore: old")
    gitops.create_tag(repo.path, "v1.0.1", old)
    repo.write("a", "1")
    new = repo.commit("chore: new")
    msg = f"v1.0.1 already exists at {old[:7]}, not {new[:7]}; tags never move"
    with pytest.raises(TagError, match=msg):
        ensure_tags(repo.path, ["fresh", "v1.0.1"], new)
    assert gitops.tag_target(repo.path, "fresh") is None
    assert gitops.tag_target(repo.path, "v1.0.1") == old


def test_cli_tag(repo, capsys):
    from version_bump.cli import main

    repo.write(
        ".github/version-bump.toml",
        '[[stream]]\nname = "s0"\nsource = { file = "v.json", format = "json-semver" }\n'
        'tag = "v{version}"\n',
    )
    repo.write("v.json", '{"major": 1, "minor": 0, "patch": 1}')
    sha = repo.commit("chore(version): bump s0 to 1.0.1")
    plan_file = repo.path / "plan.json"
    plan_file.write_text(fake_plan(sha, "v1.0.1").to_json())
    assert main(["--repo", str(repo.path), "tag", "--plan", str(plan_file)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out == {"created": ["v1.0.1"], "existing": [], "all": ["v1.0.1"]}
    assert gitops.tag_target(repo.path, "v1.0.1") == sha
