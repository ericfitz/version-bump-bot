import pytest

from version_bump.pathglob import all_match, matches, matches_any

SKIP = ["docs/**", "PROGRESS.md", "**/*.md"]


@pytest.mark.parametrize(
    "pattern,path,expected",
    [
        ("docs/**", "docs/a.md", True),
        ("docs/**", "docs/sub/deep/x.txt", True),
        ("docs/**", "docs", False),
        ("docs/**", "api/docs/a.md", False),
        ("**/*.md", "README.md", True),  # zero leading segments
        ("**/*.md", "docs/superpowers/specs/2026-01-01-x.md", True),
        ("**/*.md", "README.mdx", False),
        ("*.md", "README.md", True),
        ("*.md", "docs/a.md", False),  # `*` does not cross `/`
        ("PROGRESS.md", "PROGRESS.md", True),
        ("PROGRESS.md", "sub/PROGRESS.md", False),
        ("api-schema/tmi-openapi.json", "api-schema/tmi-openapi.json", True),
        ("src/**", "src/version_bump/cli.py", True),
        (".github/workflows/bump*", ".github/workflows/bump.yml", True),
        (".github/workflows/bump*", ".github/workflows/version.yml", False),
        ("src/?.py", "src/a.py", True),
        ("src/?.py", "src/ab.py", False),
        ("a/**/b", "a/b", True),
        ("a/**/b", "a/x/y/b", True),
        ("a.b", "aXb", False),  # regex metacharacters are escaped
    ],
)
def test_matches(pattern, path, expected):
    assert matches(pattern, path) is expected


def test_matches_any():
    assert matches_any(SKIP, "docs/foo.md")
    assert not matches_any(SKIP, "api/version.go")


# Ported from the prototype's is-docs-only self-test cases.
def test_all_match_docs_only_cases():
    assert all_match(SKIP, ["docs/foo.md", "PROGRESS.md", "README.md"])
    assert all_match(SKIP, ["docs/superpowers/specs/2026-01-01-x.md"])
    assert not all_match(SKIP, ["docs/foo.md", "api/version.go"])
    assert not all_match(SKIP, ["api-schema/tmi-openapi.json"])
    assert all_match(SKIP, [])  # nothing non-doc changed


def test_all_match_with_no_patterns_is_false_unless_empty():
    assert not all_match([], ["x"])
    assert all_match([], [])
