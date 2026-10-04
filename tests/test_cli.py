import json
import subprocess
import sys

from version_bump.cli import main

MINIMAL_CFG = """
[[stream]]
name = "bot"
source = { file = "pyproject.toml", format = "toml-path", path = "project.version" }
tag = "v{version}"
"""


def test_no_command_prints_help_and_exits_2(capsys):
    assert main([]) == 2
    assert "usage: version-bump" in capsys.readouterr().out


def test_module_entry_point_runs():
    proc = subprocess.run(
        [sys.executable, "-m", "version_bump", "--version"],
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        check=False,
    )
    assert proc.returncode == 0
    assert proc.stdout.startswith("version-bump ")


def test_cli_plan_prints_json(repo, capsys):
    repo.write(".github/version-bump.toml", MINIMAL_CFG)
    repo.write("pyproject.toml", '[project]\nname = "x"\nversion = "0.1.0"\n')
    repo.commit("chore: init")
    repo.write("src.py", "x = 1\n")
    repo.commit("feat: thing")
    assert main(["--repo", str(repo.path), "plan"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["streams"][0]["to"] == "0.2.0"


def test_cli_error_prints_one_line_and_exits_1(repo, capsys):
    assert main(["--repo", str(repo.path), "plan"]) == 1
    err = capsys.readouterr().err
    assert err.startswith("error: config file not found") and err.count("\n") == 1


def test_cli_unparsable_source_one_line_error(repo, capsys):
    repo.write(".github/version-bump.toml", MINIMAL_CFG)
    repo.write("pyproject.toml", '[project]\nname = "x"\nversion = "0.1.0"\n')
    repo.commit("chore: init")
    repo.write("pyproject.toml", "[project\n")
    repo.commit("fix: break it")
    assert main(["--repo", str(repo.path), "plan"]) == 1
    err = capsys.readouterr().err
    assert err.startswith("error: stream 'bot'") and "pyproject.toml" in err
    assert err.count("\n") == 1 and "Traceback" not in err


def test_cli_plan_ref_and_worktree_flags(repo, capsys):
    repo.write(".github/version-bump.toml", MINIMAL_CFG)
    repo.write("pyproject.toml", '[project]\nname = "x"\nversion = "0.1.0"\n')
    first = repo.commit("chore: init")
    repo.write("src.py", "x = 1\n")
    repo.commit("feat: thing")
    assert main(["--repo", str(repo.path), "plan", "--ref", first]) == 0
    assert json.loads(capsys.readouterr().out)["streams"] == []
    repo.write("pyproject.toml", '[project]\nname = "x"\nversion = "0.2.0"\n')
    assert main(["--repo", str(repo.path), "plan", "--worktree"]) == 0
    assert json.loads(capsys.readouterr().out)["base"] == "WORKTREE"
