"""Locate a scalar's byte span in JSON text by dotted path, without re-serialising."""

from __future__ import annotations

import copy
import json
from collections.abc import Iterable
from typing import Any

from version_bump.errors import FormatError

_WS = " \t\r\n"


def split_path(path: str) -> list[str]:
    parts = path.split(".")
    if not path or any(p == "" for p in parts):
        raise FormatError(f"invalid JSON path {path!r}")
    return parts


def delete_json_paths(obj: Any, paths: Iterable[str]) -> Any:
    """Return a deep copy of obj with each dotted path removed (missing paths ignored)."""
    out = copy.deepcopy(obj)
    for path in paths:
        parts = split_path(path)
        node = out
        for key in parts[:-1]:
            if not isinstance(node, dict) or key not in node:
                node = None
                break
            node = node[key]
        if isinstance(node, dict):
            node.pop(parts[-1], None)
    return out


class _Scanner:
    def __init__(self, text: str) -> None:
        self.text = text
        self.i = 0

    def skip_ws(self) -> None:
        while self.i < len(self.text) and self.text[self.i] in _WS:
            self.i += 1

    def scan_string(self) -> tuple[int, int, str]:
        """At an opening quote: return (start, end, decoded value)."""
        start = self.i
        assert self.text[self.i] == '"'
        self.i += 1
        while self.i < len(self.text):
            c = self.text[self.i]
            if c == "\\":
                self.i += 2
                continue
            if c == '"':
                self.i += 1
                return start, self.i, json.loads(self.text[start : self.i])
            self.i += 1
        raise FormatError("invalid JSON: unterminated string")

    def scan_scalar(self) -> tuple[int, int]:
        start = self.i
        while self.i < len(self.text) and self.text[self.i] not in _WS + ",]}":
            self.i += 1
        return start, self.i

    def skip_value(self) -> None:
        self.skip_ws()
        c = self.text[self.i]
        if c == '"':
            self.scan_string()
        elif c == "{":
            self.skip_container("{", "}")
        elif c == "[":
            self.skip_container("[", "]")
        else:
            self.scan_scalar()

    def skip_container(self, open_ch: str, close_ch: str) -> None:
        depth = 0
        while self.i < len(self.text):
            c = self.text[self.i]
            if c == '"':
                self.scan_string()
                continue
            if c == open_ch:
                depth += 1
            elif c == close_ch:
                depth -= 1
                if depth == 0:
                    self.i += 1
                    return
            self.i += 1
        raise FormatError("invalid JSON: unterminated container")

    def find(self, parts: list[str], path: str) -> tuple[int, int]:
        """Descend into the object at self.i following parts; return the scalar's span."""
        self.skip_ws()
        if self.i >= len(self.text) or self.text[self.i] != "{":
            raise FormatError(f"JSON path {path!r} not found: expected an object")
        self.i += 1
        want = parts[0]
        while True:
            self.skip_ws()
            if self.i >= len(self.text):
                raise FormatError("invalid JSON: unterminated object")
            if self.text[self.i] == "}":
                raise FormatError(f"JSON path {path!r} not found")
            if self.text[self.i] == ",":
                self.i += 1
                continue
            _, _, key = self.scan_string()
            self.skip_ws()
            if self.text[self.i] != ":":
                raise FormatError("invalid JSON: expected ':'")
            self.i += 1
            self.skip_ws()
            if key != want:
                self.skip_value()
                continue
            if len(parts) == 1:
                c = self.text[self.i]
                if c in "{[":
                    raise FormatError(f"JSON path {path!r} is not a scalar")
                if c == '"':
                    s, e, _ = self.scan_string()
                    return s, e
                return self.scan_scalar()
            return self.find(parts[1:], path)


def locate_json_keys(text: str, keys: list[str]) -> tuple[int, int]:
    """Span of the scalar at an explicit key list (keys may contain '.', '/' or be empty)."""
    try:
        json.loads(text)
    except json.JSONDecodeError as exc:
        raise FormatError(f"invalid JSON: {exc.msg} at line {exc.lineno}") from None
    return _Scanner(text).find(keys, "/".join(keys))


def locate_json_value(text: str, path: str) -> tuple[int, int]:
    return locate_json_keys(text, split_path(path))
