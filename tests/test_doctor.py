import json
import subprocess
from pathlib import Path

import pytest

from version_bump.doctor import Finding, detect_repo_slug, format_report, run_doctor

FIX = Path(__file__).parent / "fixtures" / "doctor"
CFG = '[[stream]]\nname = "s"\nsource = { file = "v.json", format = "json-semver" }\n'


def fetcher(repo="repo_ok", rulesets="rulesets_ok", ruleset="ruleset_ok"):
    table = {
        "repos/ericfitz/example": f"{repo}.json",
        "repos/ericfitz/example/rulesets?targets=branch": f"{rulesets}.json",
        "repos/ericfitz/example/rulesets/42": f"{ruleset}.json",
    }
    calls = []

    def fetch(path):
        calls.append(path)
        return json.loads((FIX / table[path]).read_text())

    fetch.calls = calls
    return fetch


@pytest.fixture
def cfg_path(tmp_path):
    p = tmp_path / "version-bump.toml"
    p.write_text(CFG)
    return p


def test_all_ok(cfg_path):
    fetch = fetcher()
    findings = run_doctor("ericfitz/example", cfg_path, fetch, app_id=123456)
    assert all(f.ok for f in findings), format_report(findings)
    assert [f.check for f in findings] == [
        "config",
        "merge settings",
        "bypass actor",
        "required check",
    ]
    assert all(p.startswith("repos/") for p in fetch.calls)  # read-only GETs only


def test_bad_settings_print_fix_commands(cfg_path):
    findings = run_doctor(
        "ericfitz/example",
        cfg_path,
        fetcher(repo="repo_bad", ruleset="ruleset_bad"),
        app_id=123456,
    )
    by = {f.check: f for f in findings}
    assert not by["merge settings"].ok
    assert "gh api -X PATCH repos/ericfitz/example" in by["merge settings"].fix
    assert "squash_merge_commit_title=PR_TITLE" in by["merge settings"].fix
    assert not by["bypass actor"].ok and "15368" in by["bypass actor"].detail
    assert "gh api -X PUT repos/ericfitz/example/rulesets/42" in by["bypass actor"].fix
    fixed = json.loads(by["bypass actor"].fix.split("<<'JSON'\n", 1)[1].rsplit("\nJSON", 1)[0])
    assert fixed["bypass_actors"] == [
        {"actor_id": 123456, "actor_type": "Integration", "bypass_mode": "always"}
    ]
    contexts = [
        c["context"]
        for r in fixed["rules"]
        if r["type"] == "required_status_checks"
        for c in r["parameters"]["required_status_checks"]
    ]
    assert "guard / Version Guard" in contexts
    assert not by["required check"].ok and "Version Guard" in by["required check"].detail


def test_no_ruleset_prints_post(cfg_path):
    findings = run_doctor(
        "ericfitz/example", cfg_path, fetcher(rulesets="rulesets_none"), app_id=123456
    )
    by = {f.check: f for f in findings}
    assert not by["bypass actor"].ok
    assert "gh api -X POST repos/ericfitz/example/rulesets" in by["bypass actor"].fix


def test_missing_app_id_cannot_verify_actor(cfg_path):
    findings = run_doctor("ericfitz/example", cfg_path, fetcher(), app_id=None)
    by = {f.check: f for f in findings}
    assert by["bypass actor"].ok  # exactly one Integration actor; id unverified
    assert "--app-id" in by["bypass actor"].detail


def test_invalid_config_is_a_finding(tmp_path):
    p = tmp_path / "bad.toml"
    p.write_text("[[stream]]\nname = 'x'\n")
    findings = run_doctor("ericfitz/example", p, fetcher(), app_id=123456)
    assert not findings[0].ok and findings[0].check == "config"


def test_format_report():
    text = format_report([Finding(True, "a", "fine", None), Finding(False, "b", "bad", "gh api x")])
    assert "OK   a: fine" in text and "FAIL b: bad" in text and "  fix: gh api x" in text


def test_detect_repo_slug(repo, monkeypatch):
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    assert detect_repo_slug(repo.path) is None  # no remote in scratch repos, by design
    # setting the config value only; no remote operation touches the network
    subprocess.run(
        ["git", "config", "remote.origin.url", "git@github.com:ericfitz/example.git"],
        cwd=repo.path,
        stdin=subprocess.DEVNULL,
        check=True,
    )
    assert detect_repo_slug(repo.path) == "ericfitz/example"
    monkeypatch.setenv("GITHUB_REPOSITORY", "other/repo")
    assert detect_repo_slug(repo.path) == "other/repo"


def test_multiple_rulesets_and_custom_check_name(cfg_path):
    findings = run_doctor(
        "ericfitz/example", cfg_path, fetcher(), app_id=123456, check_name="Other Check"
    )
    by = {f.check: f for f in findings}
    assert not by["required check"].ok and "Other Check" in by["required check"].detail


def test_report_heredoc_fix_is_pasteable(cfg_path):
    findings = run_doctor(
        "ericfitz/example", cfg_path, fetcher(ruleset="ruleset_bad"), app_id=123456
    )
    lines = format_report(findings).splitlines()
    assert "JSON" in lines  # terminator unindented
    start = next(i for i, ln in enumerate(lines) if "<<'JSON'" in ln)
    end = lines.index("JSON", start)
    assert lines[start].startswith("gh api -X PUT")
    json.loads("\n".join(lines[start + 1 : end]))
    script = "\n".join(lines[start : end + 1])
    proc = subprocess.run(["bash", "-n"], input=script, text=True, capture_output=True, check=False)
    assert proc.returncode == 0, proc.stderr


def _fix_body(finding):
    return json.loads(finding.fix.split("<<'JSON'\n", 1)[1].rsplit("\nJSON", 1)[0])


def test_no_app_id_fix_keeps_existing_actor(cfg_path, tmp_path):
    findings = run_doctor(
        "ericfitz/example", cfg_path, fetcher(ruleset="ruleset_missing_check"), app_id=None
    )
    by = {f.check: f for f in findings}
    assert by["bypass actor"].ok and not by["required check"].ok
    assert _fix_body(by["required check"])["bypass_actors"] == [
        {"actor_id": 123456, "actor_type": "Integration", "bypass_mode": "always"}
    ]
    assert "placeholder" not in by["required check"].detail


def test_no_app_id_no_actor_placeholder_is_explicit(cfg_path):
    findings = run_doctor(
        "ericfitz/example", cfg_path, fetcher(rulesets="rulesets_none"), app_id=None
    )
    by = {f.check: f for f in findings}
    assert "--app-id" in by["bypass actor"].detail
    assert _fix_body(by["bypass actor"])["bypass_actors"][0]["actor_id"] == 0


def _cli_fetch(monkeypatch, **kw):
    from version_bump import cli

    inner = fetcher(**kw)
    monkeypatch.setattr(cli, "gh_fetch", inner)


def test_cmd_doctor_exit_codes_and_env_app_id(repo, monkeypatch, capsys):
    from version_bump.cli import main

    repo.write(".github/version-bump.toml", CFG)
    monkeypatch.delenv("VERSION_BUMP_APP_ID", raising=False)
    args = ["--repo", str(repo.path), "doctor", "--repo-slug", "ericfitz/example"]
    _cli_fetch(monkeypatch)
    assert main([*args, "--app-id", "123456"]) == 0
    assert "FAIL" not in capsys.readouterr().out
    # env fallback: a wrong App id fails, the right one passes
    monkeypatch.setenv("VERSION_BUMP_APP_ID", "999")
    assert main(args) == 1
    assert "expected App 999" in capsys.readouterr().out
    monkeypatch.setenv("VERSION_BUMP_APP_ID", "123456")
    assert main(args) == 0
    _cli_fetch(monkeypatch, repo="repo_bad", ruleset="ruleset_bad")
    assert main(args) == 1
    assert "FAIL merge settings" in capsys.readouterr().out
    monkeypatch.setenv("VERSION_BUMP_APP_ID", "not-a-number")
    assert main(args) == 1
    captured = capsys.readouterr()
    assert "app id must be an integer" in captured.err and "Traceback" not in captured.err
