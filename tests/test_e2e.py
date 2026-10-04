"""The CLI sequence bump.yml runs, against a local scratch repo. No remote, no push."""

import json

from version_bump import gitops
from version_bump.cli import main

CONFIG = r"""
[merge]
skip_paths = ["docs/**", "**/*.md"]

[[stream]]
name = "server"
source = { file = ".version", format = "json-semver" }
targets = [{ file = "api/version.go", regex = 'Version = "(?P<version>\d+\.\d+\.\d+)"' }]
breaking = "minor"
tag = "v{version}"

[[stream]]
name = "schema"
source = { file = "openapi.json", format = "json-path", path = "info.version" }
trigger = { changed = ["openapi.json"], ignore_json_paths = ["info.version"] }
breaking = "major"
after = ["python3 -c \"import json; open('generated.txt','w').write(json.load(open('openapi.json'))['info']['version'])\""]
verify = ["test \"$(cat generated.txt)\" = \"$(python3 -c 'import json;print(json.load(open(\"openapi.json\"))[\"info\"][\"version\"])')\""]
tag = "schema/v{version}"
"""


def cli(repo, *args, capsys):
    rc = main(["--repo", str(repo.path), *args])
    out = capsys.readouterr()
    return rc, out.out, out.err


def test_full_bump_cycle(repo, capsys):
    repo.write(".github/version-bump.toml", CONFIG)
    repo.write(".version", '{"major": 1, "minor": 8, "patch": 16, "prerelease": ""}\n')
    repo.write("api/version.go", 'package api\n\nconst Version = "1.8.16"\n')
    repo.write("openapi.json", '{"info": {"version": "2.3.1"}, "paths": {"/a": {}}}\n')
    repo.write("generated.txt", "2.3.1")
    repo.commit("chore(version): bump server to 1.8.16, schema to 2.3.1")

    # Three merged PRs: fix, feat with a schema change, docs-only.
    repo.write("main.go", "package main // 1\n")
    repo.commit("fix: one (#2)")
    repo.write("openapi.json", '{"info": {"version": "2.3.1"}, "paths": {"/a": {}, "/b": {}}}\n')
    repo.commit("feat(api): add b (#3)")
    repo.write("docs/notes.md", "n\n")
    repo.commit("docs: notes (#4)")

    # 1. plan
    rc, out, _ = cli(repo, "plan", capsys=capsys)
    assert rc == 0
    plan = json.loads(out)
    assert {s["name"]: s["to"] for s in plan["streams"]} == {"server": "1.9.0", "schema": "2.4.0"}
    assert len(plan["pending"]) == 2
    plan_file = repo.path.parent / "plan.json"
    plan_file.write_text(out)

    # 2. apply, 3. hooks
    assert cli(repo, "apply", "--plan", str(plan_file), capsys=capsys)[0] == 0
    assert cli(repo, "hooks", "--plan", str(plan_file), capsys=capsys)[0] == 0
    assert (repo.path / "generated.txt").read_text() == "2.4.0"

    # 4. re-plan the working tree: nothing pending, tree self-consistent
    rc, out, _ = cli(repo, "plan", "--worktree", capsys=capsys)
    assert rc == 0 and json.loads(out)["streams"] == []

    # 5. commit exactly as the workflow does (git add -u, message from the plan)
    msg = repo.path.parent / "message.txt"
    msg.write_text(plan["commit_subject"] + "\n\n" + plan["commit_body"])
    repo.git("add", "-u")
    repo.git("commit", "-q", "-F", str(msg))
    assert (
        gitops.subject(repo.path, "HEAD") == "chore(version): bump server to 1.9.0, schema to 2.4.0"
    )
    assert "generated.txt" in repo.git("show", "--stat", "--format=", "HEAD")

    # 6. tags: create, then idempotent
    rc, out, _ = cli(repo, "tag", "--plan", str(plan_file), capsys=capsys)
    assert rc == 0 and json.loads(out)["created"] == ["v1.9.0", "schema/v2.4.0"]
    rc, out, _ = cli(repo, "tag", "--plan", str(plan_file), capsys=capsys)
    assert rc == 0 and json.loads(out)["existing"] == ["v1.9.0", "schema/v2.4.0"]
    assert gitops.tag_target(repo.path, "v1.9.0") == gitops.rev_parse(repo.path, "HEAD")

    # 7. no cascade: a run triggered by the bump commit plans nothing
    rc, out, _ = cli(repo, "plan", capsys=capsys)
    assert rc == 0 and json.loads(out)["streams"] == [] and json.loads(out)["pending"] == []

    # 8. guard on a PR branch: clean PR passes, hand bump fails
    base = gitops.rev_parse(repo.path, "HEAD")
    repo.git("checkout", "-q", "-b", "pr")
    repo.write("main.go", "package main // 2\n")
    repo.commit("fix: clean pr")
    assert cli(repo, "guard", "--base", base, capsys=capsys)[0] == 0
    repo.write(".version", '{"major": 2, "minor": 0, "patch": 0, "prerelease": ""}\n')
    repo.commit("fix: hand bump")
    rc, _, err = cli(repo, "guard", "--base", base, capsys=capsys)
    assert rc == 1 and ".version changed 1.9.0 -> 2.0.0" in err


def test_worktree_replan_fails_when_target_disagrees_after_partial_apply(repo, capsys):
    """A stream whose target disagrees after apply is caught by `plan --worktree`."""
    repo.write(
        ".github/version-bump.toml",
        '[[stream]]\nname = "s"\nsource = { file = "v.json", format = "json-semver" }\n'
        'targets = [{ file = "t.txt", regex = "v=(?P<version>\\\\d+\\\\.\\\\d+\\\\.\\\\d+)" }]\n',
    )
    repo.write("v.json", '{"major": 1, "minor": 0, "patch": 0}')
    repo.write("t.txt", "v=1.0.0\n")
    repo.commit("chore(version): seed")
    repo.write("x", "x")
    repo.commit("fix: x")
    # Simulate a broken apply that only wrote the source.
    repo.write("v.json", '{"major": 1, "minor": 0, "patch": 1}')
    rc, _, err = cli(repo, "plan", "--worktree", capsys=capsys)
    assert rc == 1 and "t.txt has 1.0.0, source has 1.0.1" in err
