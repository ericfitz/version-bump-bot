import pytest

from version_bump.errors import HookError
from version_bump.shell import run_commands


def test_run_commands_runs_in_repo_and_returns_commands(tmp_path, capsys):
    ran = run_commands(tmp_path, ["echo hi > out.txt", "true"], stream="s", kind="after hook")
    assert ran == ["echo hi > out.txt", "true"]
    assert (tmp_path / "out.txt").read_text() == "hi\n"
    assert capsys.readouterr().err.splitlines() == ["+ echo hi > out.txt", "+ true"]


def test_run_commands_failure_raises_with_shaped_message_and_stops(tmp_path):
    with pytest.raises(HookError) as ei:
        run_commands(tmp_path, ["exit 3", "touch never"], stream="srv", kind="verify command")
    assert str(ei.value) == "stream 'srv': verify command failed (exit 3): exit 3"
    assert not (tmp_path / "never").exists()


def test_run_commands_stdin_is_closed(tmp_path):
    # `cat` would hang on an inherited terminal/pipe; with DEVNULL it reads EOF and exits 0.
    assert run_commands(tmp_path, ["cat"], stream="s", kind="after hook") == ["cat"]
