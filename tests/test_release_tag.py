import re
import tomllib
from pathlib import Path

from version_bump.config import load_config

ROOT = Path(__file__).resolve().parents[1]
CONST_RE = re.compile(r"^\s*VERSION_BUMP_BOT_REF: v(\d+\.\d+\.\d+)\s*$", re.MULTILINE)


def project_version() -> str:
    return tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]


def test_embedded_release_tag_matches_pyproject_in_every_reusable_workflow():
    for name in ("bump.yml", "guard.yml"):
        text = (ROOT / ".github" / "workflows" / name).read_text()
        found = CONST_RE.findall(text)
        assert len(found) == 1, f"{name}: expected exactly one VERSION_BUMP_BOT_REF, found {found}"
        assert found[0] == project_version(), (
            f"{name} embeds v{found[0]} but pyproject.toml says {project_version()}"
        )


def test_self_adoption_config_targets_both_reusable_workflows():
    cfg = load_config(ROOT / ".github" / "version-bump.toml")
    stream = cfg.stream("version-bump-bot")
    assert stream.source.file == "pyproject.toml" and stream.source.path == "project.version"
    assert {t.file for t in stream.targets} == {
        ".github/workflows/bump.yml",
        ".github/workflows/guard.yml",
    }
    assert stream.tag == "v{version}"
