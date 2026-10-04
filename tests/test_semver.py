import pytest

from version_bump.errors import FormatError
from version_bump.semver import Version, bump_level


def test_parse_and_str():
    assert str(Version.parse("1.8.16")) == "1.8.16"
    assert Version.parse("1.8.16") == Version(1, 8, 16)


@pytest.mark.parametrize("bad", ["1.8", "v1.8.16", "1.8.16-rc1", "", "a.b.c", "01.2.3"])
def test_parse_rejects_non_semver(bad):
    with pytest.raises(FormatError):
        Version.parse(bad)


def test_bump_levels():
    v = Version(1, 8, 16)
    assert v.bump("patch") == Version(1, 8, 17)
    assert v.bump("minor") == Version(1, 9, 0)
    assert v.bump("major") == Version(2, 0, 0)


# Cases from scripts/ci-version-bump.sh self-test, server stream (breaking = minor).
@pytest.mark.parametrize(
    "subject,expected",
    [
        ("feat: add widget export", "minor"),
        ("feat(scope)!: breaking widget rewrite", "minor"),
        ("fix: correct widget off-by-one", "patch"),
        ("chore(deps): bump golang.org/x/net", "patch"),
        ("feat(api): add pagination cursor", "minor"),
        ("docs: update readme", "patch"),
        ("refactor(auth): simplify token check", "patch"),
    ],
)
def test_bump_level_breaking_minor(subject, expected):
    assert bump_level(subject, "minor") == expected


# Cases from the schema stream (breaking = major).
@pytest.mark.parametrize(
    "subject,expected",
    [
        ("fix: typo", "patch"),
        ("feat: add endpoint", "minor"),
        ("feat(api)!: breaking rewrite", "major"),
        ("fix: patch bump", "patch"),
        ("chore!: breaking chore", "major"),
        ("feat(x)!: y", "major"),
        ("fix(a): revert (b)!: c", "patch"),
        ("fix(scope): a (b) c", "patch"),
    ],
)
def test_bump_level_breaking_major(subject, expected):
    assert bump_level(subject, "major") == expected


@pytest.mark.parametrize(
    "subject",
    [
        "Feat: capitalised type",
        "  fix: leading space",
        "",
        "Merge pull request #5 from x/y",
        "feat",
    ],
)
def test_bump_level_non_conventional_is_patch(subject):
    assert bump_level(subject, "major") == "patch"


def test_fold_sequence_matches_prototype():
    # fix + feat + fix on 1.8.16 -> 1.9.1 (prototype case "fold of fix+feat(schema)+fix")
    v = Version.parse("1.8.16")
    for subject in ["fix: one (#2)", "feat(api): add b (#3)", "fix: two (#4)"]:
        v = v.bump(bump_level(subject, "minor"))
    assert str(v) == "1.9.1"
