from pathlib import Path

import pytest

from version_bump.config import Config, load_config, parse_config
from version_bump.errors import ConfigError

TMI = r"""
[merge]
skip_paths = ["docs/**", "PROGRESS.md", "**/*.md"]

[[stream]]
name = "server"
source = { file = ".version", format = "json-semver" }
targets = [
  { file = "api/version.go", regex = 'VersionMajor = "(?P<major>\d+)"' },
  { file = "api/version.go", regex = 'VersionMinor = "(?P<minor>\d+)"' },
  { file = "api/version.go", regex = 'VersionPatch = "(?P<patch>\d+)"' },
]
breaking = "minor"
tag = "v{version}"

[[stream]]
name = "schema"
source = { file = "api-schema/tmi-openapi.json", format = "json-path", path = "info.version" }
trigger = { changed = ["api-schema/tmi-openapi.json"], ignore_json_paths = ["info.version"] }
breaking = "major"
after = ["make generate-api"]
verify = ["scripts/check-embedded-spec.sh"]
"""

MINIMAL = """
[[stream]]
name = "bot"
source = { file = "pyproject.toml", format = "toml-path", path = "project.version" }
"""


def test_parse_full_example():
    cfg = parse_config(TMI)
    assert cfg.skip_paths == ("docs/**", "PROGRESS.md", "**/*.md")
    server, schema = cfg.streams
    assert server.name == "server"
    assert server.source.format == "json-semver"
    assert [t.format for t in server.targets] == ["regex"] * 3
    assert server.breaking == "minor"
    assert server.tag == "v{version}"
    assert server.trigger is None
    assert schema.trigger.changed == ("api-schema/tmi-openapi.json",)
    assert schema.trigger.ignore_json_paths == ("info.version",)
    assert schema.after == ("make generate-api",)
    assert schema.verify == ("scripts/check-embedded-spec.sh",)
    assert cfg.stream("schema") is schema


def test_parse_minimal_defaults():
    cfg = parse_config(MINIMAL)
    assert cfg.skip_paths == ()
    s = cfg.streams[0]
    assert s.breaking == "major"
    assert s.targets == () and s.after == () and s.verify == () and s.tag is None


@pytest.mark.parametrize(
    "text,msg",
    [
        ("", "at least one"),
        ("[[stream]]\nsource = { file = 'x', format = 'json-semver' }\n", "stream\\[0\\].name"),
        (MINIMAL + MINIMAL, "duplicate stream name 'bot'"),
        (MINIMAL.replace('name = "bot"', 'name = "a b"'), "stream\\[0\\].name"),
        (MINIMAL + 'breaking = "patch"\n', "stream 'bot': breaking"),
        (MINIMAL + 'tag = "release"\n', "stream 'bot': tag"),
        (MINIMAL + 'trigger = { ignore_json_paths = ["x"] }\n', "trigger.changed"),
        (MINIMAL + "trigger = { changed = [] }\n", "trigger.changed"),
        (MINIMAL + "after = [1]\n", "stream 'bot': after"),
        (MINIMAL + "bogus = 1\n", "unknown key 'bogus'"),
        ("[merge]\nskip = []\n" + MINIMAL, "unknown key 'skip'"),
        (MINIMAL + 'targets = [{ file = "x" }]\n', "targets\\[0\\]"),
        (MINIMAL.replace("toml-path", "nope"), "unknown format"),
        ("not = [toml\n", "invalid TOML"),
        (MINIMAL.replace('"project.version"', "5"), "stream 'bot': source: path must be a string"),
        (
            MINIMAL + 'targets = [{ file = "x", regex = ["a"] }]\n',
            "stream 'bot': targets\\[0\\]: regex must be a string",
        ),
    ],
)
def test_parse_errors(text, msg):
    with pytest.raises(ConfigError, match=msg):
        parse_config(text)


def test_load_config_missing(tmp_path: Path):
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / ".github" / "version-bump.toml")


def test_load_config_reads_file(tmp_path: Path):
    p = tmp_path / "version-bump.toml"
    p.write_text(MINIMAL)
    assert isinstance(load_config(p), Config)


def test_unknown_stream_name():
    with pytest.raises(ConfigError, match="no stream named 'x'"):
        parse_config(MINIMAL).stream("x")
