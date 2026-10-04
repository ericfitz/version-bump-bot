import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.yml"))


def test_expected_workflows_exist():
    names = {p.name for p in WORKFLOWS}
    assert {"ci.yml", "bump.yml", "guard.yml", "release-alias.yml"} <= names


def test_actionlint_passes():
    exe = shutil.which("actionlint")
    if exe is None:
        if os.environ.get("ACTIONLINT_REQUIRED") == "1":
            pytest.fail("actionlint is required in CI but was not found on PATH")
        pytest.skip("actionlint not installed; CI runs it (ACTIONLINT_REQUIRED=1)")
    proc = subprocess.run(
        [exe, *map(str, WORKFLOWS)],
        cwd=ROOT,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_bump_workflow_never_interpolates_plan_strings_into_shell():
    text = (ROOT / ".github/workflows/bump.yml").read_text()
    assert "git commit -F" in text
    assert '-m "${{' not in text
    assert "private-key: ${{ secrets.VERSION_BUMP_APP_PRIVATE_KEY }}" in text
    assert "echo ${{ secrets" not in text


def test_every_action_in_reusable_and_alias_workflows_is_sha_pinned():
    pinned = re.compile(r"^(\./\S*|[\w.-]+/[\w./-]+@[0-9a-f]{40})$")
    for name in ("bump.yml", "guard.yml", "release-alias.yml"):
        text = (ROOT / ".github" / "workflows" / name).read_text()
        uses = re.findall(r"^\s*(?:-\s+)?uses:\s*(\S+)", text, re.MULTILINE)
        assert uses, f"{name}: no uses: found"
        for ref in uses:
            assert pinned.match(ref), f"{name}: {ref} is not a local path or pinned to a 40-hex SHA"


def test_bump_pushes_branch_and_tags_in_one_atomic_push():
    text = (ROOT / ".github/workflows/bump.yml").read_text()
    pushes = re.findall(r"^\s*(?:if\s+)?git push\b.*$", text, re.MULTILINE)
    assert len(pushes) == 1, pushes
    assert "--atomic" in pushes[0]
    assert "refs/heads/" in pushes[0]
    assert "TAG_REFS" in pushes[0]
    assert "Create and push release tags" not in text
    assert "steps.push.outputs.pushed" not in text
    # tags are created locally (before the push), right after the commit
    assert (
        text.index("git commit -F")
        < text.index('version-bump --config "$CONFIG" tag')
        < text.index("git push")
    )


RESUME = re.compile(r'echo "::\$\{?\w+\}?::"')


def test_bump_prints_of_commit_derived_text_are_wrapped_in_stop_commands():
    lines = (ROOT / ".github/workflows/bump.yml").read_text().splitlines()
    printers = [
        i
        for i, ln in enumerate(lines)
        if ln.strip().startswith('cat "$RUNNER_TEMP/') or "git --no-pager log" in ln
    ]
    assert len(printers) >= 4, printers  # plan, replan, git log, tags
    for i in printers:
        stops = [j for j, ln in enumerate(lines[:i]) if "::stop-commands::" in ln]
        assert stops, f"line {i + 1}: print without a preceding ::stop-commands::"
        assert not any(RESUME.search(ln) for ln in lines[stops[-1] + 1 : i]), (
            f"line {i + 1}: print outside the stopped region"
        )
        assert any(RESUME.search(ln) for ln in lines[i + 1 : i + 4]), (
            f"line {i + 1}: no resume token after the print"
        )
    assert "uuidgen" in "\n".join(lines)


def test_bump_emits_plan_warnings_escaped():
    text = (ROOT / ".github/workflows/bump.yml").read_text()
    plan_step = text[text.index("- name: Plan") : text.index("bumped=")]
    assert "::warning::" in plan_step
    assert 'gsub("%";"%25")' in plan_step
    assert 'gsub("\\r";"%0D")' in plan_step and 'gsub("\\n";"%0A")' in plan_step
