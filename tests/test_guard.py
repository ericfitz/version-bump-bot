import pytest

from version_bump.config import parse_config
from version_bump.errors import GuardError, HookError
from version_bump.guard import check_values, guard, run_verify

CONFIG = r"""
[[stream]]
name = "server"
source = { file = ".version", format = "json-semver" }
targets = [{ file = "api/version.go", regex = 'Version = "(?P<version>\d+\.\d+\.\d+)"' }]

[[stream]]
name = "schema"
source = { file = "openapi.json", format = "json-path", path = "info.version" }
verify = ["test \"$(cat generated.txt)\" = \"$(python3 -c 'import json;print(json.load(open(\"openapi.json\"))[\"info\"][\"version\"])')\""]
"""


def seed(repo):
    repo.write(".version", '{"major": 1, "minor": 8, "patch": 16}\n')
    repo.write("api/version.go", 'package api\n\nconst Version = "1.8.16"\n')
    repo.write("openapi.json", '{"info": {"version": "2.3.1"}, "paths": {}}\n')
    repo.write("generated.txt", "2.3.1")
    repo.write("api/api.go", "// generated: 2.3.1\n")
    return repo.commit("chore(version): seed")


@pytest.fixture
def cfg():
    return parse_config(CONFIG)


def test_code_only_pr_passes(repo, cfg):
    base = seed(repo)
    repo.write("main.go", "x\n")
    repo.commit("fix: code only")
    r = check_values(repo.path, cfg, base, "HEAD")
    assert r.violations == [] and r.skipped == []


def test_hand_edited_source_fails(repo, cfg):
    base = seed(repo)
    repo.write(".version", '{"major": 9, "minor": 0, "patch": 0}\n')
    repo.commit("fix: hand bump")
    r = check_values(repo.path, cfg, base, "HEAD")
    assert r.violations == [
        "server: .version changed 1.8.16 -> 9.0.0; only the post-merge bump may write it"
    ]


def test_hand_edited_target_fails(repo, cfg):
    base = seed(repo)
    repo.write("api/version.go", 'package api\n\nconst Version = "1.8.17"\n')
    repo.commit("fix: hand target bump")
    r = check_values(repo.path, cfg, base, "HEAD")
    assert r.violations == [
        "server: api/version.go changed 1.8.16 -> 1.8.17; only the post-merge bump may write it"
    ]


def test_hand_edited_json_path_fails(repo, cfg):
    base = seed(repo)
    repo.write("openapi.json", '{"info": {"version": "9.9.9"}, "paths": {}}\n')
    repo.commit("fix: hand schema bump")
    r = check_values(repo.path, cfg, base, "HEAD")
    assert r.violations == [
        "schema: openapi.json changed 2.3.1 -> 9.9.9; only the post-merge bump may write it"
    ]


def test_regenerated_file_only_passes(repo, cfg):
    base = seed(repo)
    repo.write("api/api.go", "// generated: 2.3.1 (regenerated, different bytes)\n")
    repo.write("openapi.json", '{"info": {"version": "2.3.1"}, "paths": {"/new": {}}}\n')
    repo.commit("feat: schema change without version edit")
    assert check_values(repo.path, cfg, base, "HEAD").violations == []


def test_guard_skips_stream_whose_source_is_absent_at_base(repo, cfg):
    repo.write("main.go", "x\n")
    base = repo.commit("chore: before adoption")
    seed(repo)  # the adopting PR adds every version file
    r = check_values(repo.path, cfg, base, "HEAD")
    assert r.violations == []
    assert r.skipped == [
        "server: source .version absent at base (new stream); skipped",
        "schema: source openapi.json absent at base (new stream); skipped",
    ]


def test_run_verify_pass_and_fail(repo, cfg):
    seed(repo)
    assert run_verify(repo.path, cfg) == list(cfg.streams[1].verify)
    repo.write("generated.txt", "stale")
    with pytest.raises(HookError, match="verify command failed"):
        run_verify(repo.path, cfg)


def test_guard_reports_violations_before_verify(repo, cfg):
    base = seed(repo)
    repo.write(".version", '{"major": 9, "minor": 0, "patch": 0}\n')
    repo.write("generated.txt", "stale")
    repo.commit("fix: both wrong")
    with pytest.raises(GuardError, match=r"\.version changed"):
        guard(repo.path, cfg, base, "HEAD")


def test_cli_guard(repo, cfg, capsys):
    from version_bump.cli import main

    repo.write(".github/version-bump.toml", CONFIG)
    base = seed(repo)
    repo.write("main.go", "x\n")
    repo.commit("fix: code only")
    assert main(["--repo", str(repo.path), "guard", "--base", base]) == 0
    assert capsys.readouterr().out.startswith("OK: version state untouched (2 stream(s) checked)")
    repo.write(".version", '{"major": 9, "minor": 0, "patch": 0}\n')
    repo.commit("fix: hand bump")
    assert main(["--repo", str(repo.path), "guard", "--base", base, "--head", "HEAD"]) == 1
    assert ".version changed 1.8.16 -> 9.0.0" in capsys.readouterr().err


UV_CFG = parse_config(
    '[[stream]]\nname = "app"\n'
    'source = { file = "pyproject.toml", format = "toml-path", path = "project.version" }\n'
)


def uv_lock(version, name="app"):
    return f'[[package]]\nname = "{name}"\nversion = "{version}"\nsource = {{ editable = "." }}\n'


def seed_uv(repo, version, lock_version):
    repo.write("pyproject.toml", f'[project]\nname = "app"\nversion = "{version}"\n')
    repo.write("uv.lock", uv_lock(lock_version))
    return repo.commit("chore(version): seed")


def test_lockfile_drifting_edit_fails(repo):
    base = seed_uv(repo, "1.0.0", "1.0.0")
    repo.write("uv.lock", uv_lock("1.0.5"))
    repo.commit("fix: hand edit")
    with pytest.raises(GuardError, match=r"uv\.lock changed app 1\.0\.0 -> 1\.0\.5.*has 1\.0\.0"):
        guard(repo.path, UV_CFG, base)


def test_lockfile_repair_passes(repo):
    base = seed_uv(repo, "1.0.0", "0.1.0")
    repo.write("uv.lock", uv_lock("1.0.0"))
    repo.commit("fix: repair lock")
    result = guard(repo.path, UV_CFG, base)
    assert result.violations == [] and result.warnings == []


def test_lockfile_untouched_drift_warns(repo):
    base = seed_uv(repo, "1.0.0", "0.1.0")
    repo.write("README.txt", "hi\n")
    repo.commit("fix: unrelated")
    result = guard(repo.path, UV_CFG, base)
    assert len(result.warnings) == 1 and "uv.lock" in result.warnings[0]


def test_unusable_lockfile_is_reported_not_failed(repo):
    repo.write("pyproject.toml", '[project]\nname = "app"\nversion = "1.0.0"\n')
    repo.write("uv.lock", uv_lock("1.0.0", name="other"))
    base = repo.commit("chore(version): seed")
    repo.write("README.txt", "hi\n")
    repo.commit("fix: unrelated")
    result = guard(repo.path, UV_CFG, base)
    assert len(result.warnings) == 1 and "exactly one" in result.warnings[0]


def test_guard_failure_message_includes_warnings(repo):
    two = parse_config(
        '[[stream]]\nname = "app"\n'
        'source = { file = "pyproject.toml", format = "toml-path", path = "project.version" }\n'
        '[[stream]]\nname = "lib"\n'
        'source = { file = "lib/pyproject.toml", format = "toml-path", path = "project.version" }\n'
    )
    repo.write("pyproject.toml", '[project]\nname = "app"\nversion = "1.0.0"\n')
    repo.write("uv.lock", uv_lock("1.0.0"))
    repo.write("lib/pyproject.toml", '[project]\nname = "lib"\nversion = "2.0.0"\n')
    repo.write("lib/uv.lock", uv_lock("1.9.0", name="lib"))  # untouched drift
    base = repo.commit("chore(version): seed")
    repo.write("uv.lock", uv_lock("1.0.5"))
    repo.commit("fix: hand edit")
    with pytest.raises(
        GuardError, match=r"(?s)uv\.lock changed.*warning: lib: lib/uv\.lock records"
    ):
        guard(repo.path, two, base)
