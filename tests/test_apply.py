import json

import pytest

from version_bump.apply import apply_plan, run_hooks
from version_bump.config import parse_config
from version_bump.errors import HookError, VersionBumpError
from version_bump.plan import compute_plan

CONFIG = r"""
[[stream]]
name = "server"
source = { file = ".version", format = "json-semver" }
targets = [
  { file = "api/version.go", regex = 'VersionMajor = "(?P<major>\d+)"' },
  { file = "api/version.go", regex = 'VersionMinor = "(?P<minor>\d+)"' },
  { file = "api/version.go", regex = 'VersionPatch = "(?P<patch>\d+)"' },
]
breaking = "minor"
after = ["printf 'gen %s' \"$(cat .version | tr -d '\\n ')\" > generated.txt"]

[[stream]]
name = "lib"
source = { file = "pyproject.toml", format = "toml-path", path = "project.version" }
after = ["false"]
"""

GO = (
    'package api\n\nconst (\n\tVersionMajor = "1"\n\tVersionMinor = "8"\n\tVersionPatch = "16"\n)\n'
)


def seed(repo):
    repo.write(".version", '{"major": 1, "minor": 8, "patch": 16, "prerelease": "rc"}\r\n')
    repo.write("api/version.go", GO)
    repo.write("pyproject.toml", '[project]\nname = "x"\nversion = "0.1.0"\n')
    repo.commit("chore(version): seed")


@pytest.fixture
def cfg():
    return parse_config(CONFIG)


def test_apply_writes_source_then_targets_and_preserves_bytes(repo, cfg):
    seed(repo)
    repo.write("main.go", "x\n")
    repo.commit("feat: thing")
    plan = compute_plan(repo.path, cfg)
    written = apply_plan(repo.path, cfg, plan)
    assert written == [".version", "api/version.go", "pyproject.toml"]
    assert (
        repo.path / ".version"
    ).read_bytes() == b'{"major": 1, "minor": 9, "patch": 0, "prerelease": "rc"}\r\n'
    go = (repo.path / "api/version.go").read_text()
    assert 'VersionMajor = "1"' in go and 'VersionMinor = "9"' in go and 'VersionPatch = "0"' in go
    assert 'version = "0.2.0"' in (repo.path / "pyproject.toml").read_text()
    # Re-planning the working tree now sees nothing pending (self-consistent).
    assert compute_plan(repo.path, cfg, worktree=True).streams == []


def test_apply_rewrites_corrupted_target_from_source(repo, cfg):
    seed(repo)
    repo.write("main.go", "x\n")
    repo.commit("fix: thing")
    plan = compute_plan(repo.path, cfg)
    # Hand-corrupt a target before apply: apply must rewrite it from the source.
    repo.write("api/version.go", GO.replace('VersionPatch = "16"', 'VersionPatch = "99"'))
    apply_plan(repo.path, cfg, plan)
    assert 'VersionPatch = "17"' in (repo.path / "api/version.go").read_text()


def test_apply_rejects_stale_plan(repo, cfg):
    seed(repo)
    repo.write("main.go", "x\n")
    repo.commit("fix: thing")
    plan = compute_plan(repo.path, cfg)
    repo.write("main.go", "y\n")
    repo.commit("fix: another")
    with pytest.raises(VersionBumpError, match="stale"):
        apply_plan(repo.path, cfg, plan)


def test_apply_rejects_missing_file(repo, cfg):
    seed(repo)
    repo.write("main.go", "x\n")
    repo.commit("fix: thing")
    plan = compute_plan(repo.path, cfg)
    (repo.path / "api/version.go").unlink()
    before = (repo.path / ".version").read_bytes()
    with pytest.raises(VersionBumpError, match="api/version.go"):
        apply_plan(repo.path, cfg, plan)
    # Pre-check: nothing written before the failure (source untouched).
    assert (repo.path / ".version").read_bytes() == before
    assert 'version = "0.1.0"' in (repo.path / "pyproject.toml").read_text()


def test_run_hooks_runs_only_bumped_streams_and_fails_loudly(repo, cfg):
    seed(repo)
    repo.write("main.go", "x\n")
    repo.commit("fix: thing")
    plan = compute_plan(repo.path, cfg)
    apply_plan(repo.path, cfg, plan)
    with pytest.raises(HookError, match=r"exit 1.*false"):
        run_hooks(repo.path, plan)
    # The first stream's hook ran before the failing one.
    assert (repo.path / "generated.txt").read_text().startswith("gen {")


def test_run_hooks_skips_unbumped_streams(repo, cfg):
    seed(repo)
    only_server = parse_config(
        CONFIG.replace(
            'after = ["false"]', 'after = ["false"]\ntrigger = { changed = ["pyproject.toml"] }'
        )
    )
    repo.write("main.go", "x\n")
    repo.commit("fix: thing")
    plan = compute_plan(repo.path, only_server)
    assert [s.name for s in plan.streams] == ["server"]
    apply_plan(repo.path, only_server, plan)
    assert run_hooks(repo.path, plan) == plan.streams[0].after


def test_cli_apply_and_hooks(repo, cfg, capsys):
    from version_bump.cli import main

    repo.write(".github/version-bump.toml", CONFIG.replace('after = ["false"]', ""))
    seed(repo)
    repo.write("main.go", "x\n")
    repo.commit("fix: thing")
    plan_file = repo.path / "plan.json"
    assert main(["--repo", str(repo.path), "plan"]) == 0
    plan_file.write_text(capsys.readouterr().out)
    assert main(["--repo", str(repo.path), "apply", "--plan", str(plan_file)]) == 0
    assert capsys.readouterr().out.splitlines() == [".version", "api/version.go", "pyproject.toml"]
    assert main(["--repo", str(repo.path), "hooks", "--plan", str(plan_file)]) == 0
    assert (repo.path / "generated.txt").exists()
    assert json.loads(plan_file.read_text())["streams"][0]["to"] == "1.8.17"
