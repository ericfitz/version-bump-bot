import json

import pytest

from version_bump.errors import FormatError
from version_bump.jsonpos import delete_json_paths, locate_json_value

DOC = '{\n  "info": {"title": "x", "version": "2.3.1"},\n  "major": 1, "paths": {"/a": {}}\n}\n'


def test_locate_nested_string():
    s, e = locate_json_value(DOC, "info.version")
    assert DOC[s:e] == '"2.3.1"'


def test_locate_top_level_number():
    s, e = locate_json_value(DOC, "major")
    assert DOC[s:e] == "1"


def test_escaped_quotes_and_braces_in_strings_do_not_confuse_scanner():
    doc = '{"a": "}{\\"version\\": 9", "version": "1.0.0"}'
    s, e = locate_json_value(doc, "version")
    assert doc[s:e] == '"1.0.0"'


def test_same_key_elsewhere_is_not_matched():
    doc = '{"x": {"version": "9.9.9"}, "info": {"version": "1.2.3"}}'
    s, e = locate_json_value(doc, "info.version")
    assert doc[s:e] == '"1.2.3"'


def test_crlf_and_tabs_preserved_positions():
    doc = '{\r\n\t"version":\t"1.2.3"\r\n}\r\n'
    s, e = locate_json_value(doc, "version")
    assert doc[s:e] == '"1.2.3"'


def test_missing_path_is_error():
    with pytest.raises(FormatError, match="info.nope"):
        locate_json_value(DOC, "info.nope")


def test_non_scalar_is_error():
    with pytest.raises(FormatError, match="not a scalar"):
        locate_json_value(DOC, "info")


def test_invalid_json_is_error():
    with pytest.raises(FormatError, match="invalid JSON"):
        locate_json_value("{", "a")


def test_delete_json_paths():
    obj = json.loads(DOC)
    out = delete_json_paths(obj, ["info.version", "missing.path", "major"])
    assert out == {"info": {"title": "x"}, "paths": {"/a": {}}}
    assert "version" in json.loads(DOC)["info"]  # input not mutated
