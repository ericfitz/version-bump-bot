import pytest

from version_bump.errors import ConfigError, FormatError
from version_bump.formats import (
    Captured,
    FileSpec,
    read_full,
    read_partial,
    validate_spec,
    write_version,
)
from version_bump.semver import Version

V = Version(1, 9, 1)

JSON_SEMVER = '{\n  "major": 1,\n  "minor": 8,\n  "patch": 16,\n  "prerelease": ""\n}\n'
OPENAPI = '{"info": {"version": "2.3.1", "title": "x"}, "paths": {"/a": {}}}\n'
PYPROJECT = '[project]\nname = "x"\nversion = "0.1.0"\n\n[tool.other]\nversion = "9.9.9"\n'
GO = (
    'package api\n\nconst (\n\tVersionMajor = "1"\n\tVersionMinor = "8"\n'
    '\tVersionPatch = "16"\n\tVersionPreRelease = ""\n)\n'
)
WORKFLOW = "env:\n  VERSION_BUMP_BOT_REF: v0.1.0\n  OTHER: v0.1.0\n"


def spec(fmt, **kw):
    return FileSpec(file="f", format=fmt, path=kw.get("path"), regex=kw.get("regex"))


# --- json-semver ---------------------------------------------------------------
def test_json_semver_round_trip_preserves_bytes():
    s = spec("json-semver")
    assert read_full(JSON_SEMVER, s) == Version(1, 8, 16)
    out = write_version(JSON_SEMVER, s, V)
    assert out == '{\n  "major": 1,\n  "minor": 9,\n  "patch": 1,\n  "prerelease": ""\n}\n'
    assert read_full(out, s) == V


def test_json_semver_missing_field_is_error():
    with pytest.raises(FormatError, match="patch"):
        read_full('{"major": 1, "minor": 2}', spec("json-semver"))


def test_json_semver_non_integer_is_error():
    with pytest.raises(FormatError, match="integer"):
        read_full('{"major": "1", "minor": 2, "patch": 3}', spec("json-semver"))


# --- json-path -----------------------------------------------------------------
def test_json_path_round_trip_preserves_bytes_and_suffix():
    s = spec("json-path", path="info.version")
    assert read_full(OPENAPI, s) == Version(2, 3, 1)
    out = write_version(OPENAPI, s, Version(2, 4, 0))
    assert out == OPENAPI.replace("2.3.1", "2.4.0")
    pre = '{"version": "1.2.3-rc1"}'
    assert write_version(pre, spec("json-path", path="version"), V) == '{"version": "1.9.1-rc1"}'


def test_json_path_crlf_preserved():
    doc = '{\r\n  "version": "1.2.3"\r\n}\r\n'
    assert write_version(doc, spec("json-path", path="version"), V) == doc.replace("1.2.3", "1.9.1")


def test_json_path_non_string_is_error():
    with pytest.raises(FormatError, match="string"):
        read_full('{"version": 123}', spec("json-path", path="version"))


def test_json_path_bad_version_is_error():
    with pytest.raises(FormatError, match="MAJOR.MINOR.PATCH"):
        read_full('{"version": "v1.2"}', spec("json-path", path="version"))


# --- toml-path -----------------------------------------------------------------
def test_toml_path_round_trip_is_line_preserving():
    s = spec("toml-path", path="project.version")
    assert read_full(PYPROJECT, s) == Version(0, 1, 0)
    out = write_version(PYPROJECT, s, V)
    assert out == PYPROJECT.replace('version = "0.1.0"', 'version = "1.9.1"')
    assert 'version = "9.9.9"' in out  # the other table is untouched
    assert read_full(out, s) == V


def test_toml_path_wrong_table_is_error():
    with pytest.raises(FormatError, match="tool.nope.version"):
        read_full(PYPROJECT, spec("toml-path", path="tool.nope.version"))


def test_toml_path_dotted_key_form_is_error_on_write():
    doc = 'project.version = "0.1.0"\n'
    with pytest.raises(FormatError, match="exactly one"):
        write_version(doc, spec("toml-path", path="project.version"), V)


def test_toml_path_single_quoted_value():
    doc = "[project]\nversion = '0.1.0'\n"
    assert (
        write_version(doc, spec("toml-path", path="project.version"), V)
        == "[project]\nversion = '1.9.1'\n"
    )


# --- regex ---------------------------------------------------------------------
def test_regex_partial_targets_read_and_write():
    major = spec("regex", regex=r'VersionMajor = "(?P<major>\d+)"')
    minor = spec("regex", regex=r'VersionMinor = "(?P<minor>\d+)"')
    patch = spec("regex", regex=r'VersionPatch = "(?P<patch>\d+)"')
    assert read_partial(GO, major) == Captured(1, None, None)
    assert read_partial(GO, patch) == Captured(None, None, 16)
    out = GO
    for s in (major, minor, patch):
        out = write_version(out, s, V)
    assert (
        'VersionMajor = "1"' in out and 'VersionMinor = "9"' in out and 'VersionPatch = "1"' in out
    )
    assert 'VersionPreRelease = ""' in out
    assert out.count("\n") == GO.count("\n")


def test_regex_version_group_read_full_and_write():
    s = spec("regex", regex=r"VERSION_BUMP_BOT_REF: v(?P<version>\d+\.\d+\.\d+)")
    assert read_full(WORKFLOW, s) == Version(0, 1, 0)
    assert (
        write_version(WORKFLOW, s, V) == "env:\n  VERSION_BUMP_BOT_REF: v1.9.1\n  OTHER: v0.1.0\n"
    )


def test_regex_zero_matches_is_error():
    with pytest.raises(FormatError, match="matched 0 times"):
        read_partial(GO, spec("regex", regex=r'Nope = "(?P<major>\d+)"'))


def test_regex_two_matches_is_error():
    with pytest.raises(FormatError, match="matched 2 times"):
        read_partial(WORKFLOW, spec("regex", regex=r"v(?P<version>\d+\.\d+\.\d+)"))


def test_regex_partial_source_is_error():
    with pytest.raises(FormatError, match="minor"):
        read_full(GO, spec("regex", regex=r'VersionMajor = "(?P<major>\d+)"'))


def test_captured_matches_only_captured_components():
    assert Captured(1, None, None).matches(Version(1, 5, 5))
    assert not Captured(1, None, 3).matches(Version(1, 5, 5))
    assert Captured(None, None, None).text == "?.?.?"
    assert Captured(1, None, 3).text == "1.?.3"


# --- validate_spec -------------------------------------------------------------
@pytest.mark.parametrize(
    "s,role,msg",
    [
        (spec("nope"), "source", "unknown format"),
        (spec("json-path"), "source", "requires 'path'"),
        (spec("toml-path"), "target", "requires 'path'"),
        (spec("regex"), "source", "requires 'regex'"),
        (spec("regex", regex="("), "source", "invalid regex"),
        (spec("regex", regex="x"), "target", "named group"),
        (spec("regex", regex=r"(?P<version>\d+)(?P<major>\d+)"), "target", "either 'version'"),
        (spec("regex", regex=r"(?P<major>\d+)"), "source", "all of major, minor and patch"),
    ],
)
def test_validate_spec_errors(s, role, msg):
    with pytest.raises(ConfigError, match=msg):
        validate_spec(s, role)


def test_validate_spec_ok():
    validate_spec(spec("json-semver"), "source")
    validate_spec(spec("regex", regex=r"(?P<major>\d+)"), "target")
    validate_spec(spec("regex", regex=r"(?P<version>\d+\.\d+\.\d+)"), "source")


def test_validate_spec_malformed_path_is_config_error():
    with pytest.raises(ConfigError, match="a..b"):
        validate_spec(spec("json-path", path="a..b"), "source")


def test_json_path_non_ascii_suffix_and_escapes_preserved():
    s = spec("json-path", path="version")
    doc = '{"version": "1.2.3-caf\u00e9", "x": "a\\/b"}'
    assert write_version(doc, s, V) == doc.replace("1.2.3", "1.9.1")
    doc2 = '{"version": "1.2.3-café"}'
    assert write_version(doc2, s, V) == doc2.replace("1.2.3", "1.9.1")
    doc3 = '{"version": "1.2.3-a\\/b"}'
    assert write_version(doc3, s, V) == doc3.replace("1.2.3", "1.9.1")


def test_regex_version_group_suffix_preserved():
    s = spec("regex", regex=r"v(?P<version>\S+)")
    assert write_version("v0.1.0-rc1\n", s, V) == "v1.9.1-rc1\n"


def test_toml_array_of_tables_header_ends_project_table():
    s = spec("toml-path", path="project.version")
    doc = '[project]\nversion = "0.1.0"\n\n[[tool.x]]\nversion = "9.9.9"\n'
    assert write_version(doc, s, V) == doc.replace("0.1.0", "1.9.1")
    # `version` only lives in the [[tool.x]] section, so [project] has no such key
    doc2 = '[project]\nversion = "0.1.0"\n[[project.x]]\nversion = "9.9.9"\n'
    assert write_version(doc2, s, V) == doc2.replace("0.1.0", "1.9.1")
