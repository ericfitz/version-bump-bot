import json

import pytest

from version_bump.config import parse_config
from version_bump.errors import ConfigError, GuardError, VersionBumpError
from version_bump.plan import Plan, compute_plan, find_base, is_triggered, render_tag
from version_bump.semver import Version

CONFIG = r"""
[merge]
skip_paths = ["docs/**", "PROGRESS.md", "**/*.md"]

[[stream]]
name = "server"
source = { file = ".version", format = "json-semver" }
targets = [{ file = "api/version.go", regex = 'Version = "(?P<version>\d+\.\d+\.\d+)"' }]
breaking = "minor"
tag = "v{version}"

[[stream]]
name = "schema"
source = { file = "api-schema/openapi.json", format = "json-path", path = "info.version" }
trigger = { changed = ["api-schema/openapi.json"], ignore_json_paths = ["info.version"] }
breaking = "major"
after = ["make generate-api"]
"""


def seed(repo, server="1.8.16", schema="2.3.1", spec_paths='{"/a": {}}'):
    ma, mi, pa = server.split(".")
    repo.write(".version", f'{{"major": {ma}, "minor": {mi}, "patch": {pa}, "prerelease": ""}}\n')
    repo.write("api/version.go", f'package api\n\nconst Version = "{server}"\n')
    repo.write(
        "api-schema/openapi.json", f'{{"info": {{"version": "{schema}"}}, "paths": {spec_paths}}}\n'
    )
    repo.write("main.go", "package main\n")
    return repo.commit(f"chore(version): bump server to {server}")


@pytest.fixture
def cfg():
    return parse_config(CONFIG)


def plan_of(repo, cfg, **kw) -> Plan:
    return compute_plan(repo.path, cfg, **kw)


def test_right_after_bump_nothing_pending(repo, cfg):
    base = seed(repo)
    p = plan_of(repo, cfg)
    assert p.base == base and p.pending == [] and p.streams == []
    assert p.commit_subject == "" and p.commit_body == ""


def test_docs_only_commit_is_skipped(repo, cfg):
    seed(repo)
    repo.write("docs/a.md", "x")
    repo.write("README.md", "y")
    repo.commit("docs: notes (#1)")
    p = plan_of(repo, cfg)
    assert p.pending == [] and p.streams == []


def test_fold_fix_feat_schema_fix(repo, cfg):
    seed(repo)
    repo.write("main.go", "package main // one\n")
    c1 = repo.commit("fix: one (#2)")
    repo.write(
        "api-schema/openapi.json", '{"info": {"version": "2.3.1"}, "paths": {"/a": {}, "/b": {}}}\n'
    )
    c2 = repo.commit("feat(api): add b (#3)")
    repo.write("main.go", "package main // two\n")
    c3 = repo.commit("fix: two (#4)")
    p = plan_of(repo, cfg)
    assert [c.commit for c in p.pending] == [c1, c2, c3]
    assert [c.streams for c in p.pending] == [["server"], ["server", "schema"], ["server"]]
    server, schema = p.streams
    assert (server.from_version, server.to_version, server.tag) == ("1.8.16", "1.9.1", "v1.9.1")
    assert (schema.from_version, schema.to_version, schema.tag) == ("2.3.1", "2.4.0", None)
    assert schema.after == ["make generate-api"]
    assert server.files == [".version", "api/version.go"]  # deduplicated, source first
    assert p.commit_subject == "chore(version): bump server to 1.9.1, schema to 2.4.0"
    assert p.commit_body.startswith("Folds 3 merged commit(s):\n- " + c1[:7] + " fix: one (#2)\n")


def test_no_cascade_after_bump_commit(repo, cfg):
    seed(repo)
    repo.write("main.go", "package main // one\n")
    repo.commit("fix: one (#2)")
    bump = seed(repo, server="1.8.17")  # the bot's own commit: changes the source value
    p = plan_of(repo, cfg)
    assert p.base == bump and p.pending == [] and p.streams == []


def test_find_base_ignores_touch_without_value_change(repo, cfg):
    base = seed(repo)
    # Reformat .version without changing its value: must NOT become the base.
    repo.write(".version", '{"major":1,"minor":8,"patch":16,"prerelease":"rc1"}\n')
    touch = repo.commit("style: reformat version file")
    assert find_base(repo.path, cfg, "HEAD") == base
    p = plan_of(repo, cfg)
    assert [c.commit for c in p.pending] == [touch]
    assert [s.to_version for s in p.streams] == ["1.8.17"]


def test_breaking_levels(repo, cfg):
    seed(repo)
    repo.write("api-schema/openapi.json", '{"info": {"version": "2.3.1"}, "paths": {}}\n')
    repo.commit("feat(api)!: breaking rewrite")
    p = plan_of(repo, cfg)
    assert {s.name: s.to_version for s in p.streams} == {"server": "1.9.0", "schema": "3.0.0"}


def test_untriggered_stream_does_not_bump(repo, cfg):
    seed(repo)
    repo.write("main.go", "package main // x\n")
    repo.commit("feat: server only")
    p = plan_of(repo, cfg)
    assert [s.name for s in p.streams] == ["server"]


def test_only_ignored_json_path_change_does_not_trigger(repo, cfg):
    seed(repo)
    repo.write("api-schema/openapi.json", '{"info": {"version": "9.9.9"}, "paths": {"/a": {}}}\n')
    sha = repo.commit("fix: hand-edited version only")
    assert not is_triggered(repo.path, cfg.stream("schema"), sha, ["api-schema/openapi.json"])
    assert plan_of(repo, cfg).base == sha


def test_several_pending_commits_touching_triggered_stream(repo, cfg):
    seed(repo)
    for i in range(3):
        repo.write(
            "api-schema/openapi.json",
            f'{{"info": {{"version": "2.3.1"}}, "paths": {{"/p{i}": {{}}}}}}\n',
        )
        repo.commit(f"feat: endpoint {i}")
    p = plan_of(repo, cfg)
    assert {s.name: s.to_version for s in p.streams} == {"server": "1.11.0", "schema": "2.6.0"}


def test_plan_merge_commit_uses_first_parent_diff(repo, cfg):
    seed(repo)
    repo.git("checkout", "-q", "-b", "topic")
    repo.write("api-schema/openapi.json", '{"info": {"version": "2.3.1"}, "paths": {"/z": {}}}\n')
    repo.commit("feat: on topic")
    repo.git("checkout", "-q", "main")
    repo.write("main.go", "package main // main\n")
    repo.commit("fix: on main")
    merge = repo.merge_branch("topic", "Merge pull request #5 from x/topic")
    p = plan_of(repo, cfg)
    assert p.pending[-1].commit == merge
    assert p.pending[-1].streams == ["server", "schema"]  # first-parent diff shows the spec change
    assert {s.name: s.to_version for s in p.streams} == {"server": "1.8.18", "schema": "2.3.2"}


def test_plan_subject_with_shell_metacharacters_round_trips(repo, cfg):
    seed(repo)
    subject = "fix: `rm -rf` $(echo hi) \"quoted\" 'single' (#7)"
    repo.write("main.go", "package main // s\n")
    repo.commit(subject)
    p = plan_of(repo, cfg)
    assert p.pending[0].subject == subject
    again = Plan.from_json(p.to_json())
    assert again.pending[0].subject == subject and again.commit_body == p.commit_body


def test_plan_missing_source_at_head_is_config_error(repo, cfg):
    seed(repo)
    repo.git("rm", "-q", "api-schema/openapi.json")
    repo.commit("fix: drop spec")
    with pytest.raises(ConfigError, match="stream 'schema'.*api-schema/openapi.json"):
        plan_of(repo, cfg)


def test_no_base_is_config_error(repo, cfg):
    repo.write("main.go", "package main\n")
    repo.commit("chore: no version files yet")
    with pytest.raises(ConfigError, match="ever set a source value"):
        find_base(repo.path, cfg, "HEAD")


def test_worktree_mode_sees_virtual_bump_commit(repo, cfg):
    seed(repo)
    repo.write("main.go", "package main // one\n")
    repo.commit("fix: one (#2)")
    assert plan_of(repo, cfg).streams != []
    # Simulate apply: write the new values into the working tree (source + target).
    repo.write(".version", '{"major": 1, "minor": 8, "patch": 17, "prerelease": ""}\n')
    repo.write("api/version.go", 'package api\n\nconst Version = "1.8.17"\n')
    p = plan_of(repo, cfg, worktree=True)
    assert p.base == "WORKTREE" and p.pending == [] and p.streams == []


def test_worktree_mode_fails_when_target_disagrees(repo, cfg):
    seed(repo)
    repo.write(".version", '{"major": 1, "minor": 8, "patch": 17, "prerelease": ""}\n')
    with pytest.raises(GuardError, match="api/version.go"):
        plan_of(repo, cfg, worktree=True)


def test_worktree_mode_without_changes_equals_normal_plan(repo, cfg):
    seed(repo)
    repo.write("main.go", "package main // one\n")
    repo.commit("fix: one (#2)")
    assert plan_of(repo, cfg, worktree=True).to_dict() == plan_of(repo, cfg).to_dict()


def test_render_tag():
    assert render_tag("v{version}", Version(1, 2, 3)) == "v1.2.3"
    assert render_tag("rel-{major}.{minor}", Version(1, 2, 3)) == "rel-1.2"


def test_plan_json_shape(repo, cfg):
    seed(repo)
    repo.write("main.go", "package main // one\n")
    repo.commit("fix: one (#2)")
    d = json.loads(plan_of(repo, cfg).to_json())
    assert set(d) == {"ref", "base", "pending", "streams", "commit_subject", "commit_body"}
    assert set(d["pending"][0]) == {"commit", "subject", "streams"}
    assert set(d["streams"][0]) == {"name", "from", "to", "tag", "after", "files"}


def test_plan_unparsable_source_at_head_names_stream_and_file(repo, cfg):
    seed(repo)
    repo.write("api-schema/openapi.json", "{not json")
    repo.commit("fix: corrupt spec")
    with pytest.raises(ConfigError, match="stream 'schema'.*api-schema/openapi.json"):
        plan_of(repo, cfg)


@pytest.mark.parametrize("text", ["not json", '{"ref": "x"}', "[]"])
def test_plan_from_json_rejects_malformed(text):
    with pytest.raises(VersionBumpError, match="invalid plan JSON"):
        Plan.from_json(text)


def test_worktree_unparsable_source_names_stream_and_file(repo, cfg):
    seed(repo)
    repo.write("api-schema/openapi.json", "{not json")
    with pytest.raises(ConfigError, match="stream 'schema'.*api-schema/openapi.json"):
        plan_of(repo, cfg, worktree=True)
