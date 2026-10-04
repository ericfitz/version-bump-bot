"""Error hierarchy. The CLI prints str(error) on one line and exits 1 for any of these."""


class VersionBumpError(Exception):
    """Base class for every expected failure."""


class ConfigError(VersionBumpError):
    """The config file is missing, malformed, or semantically invalid."""


class FormatError(VersionBumpError):
    """A version file cannot be read or written in its declared format."""


class GitError(VersionBumpError):
    """A git command failed."""


class GuardError(VersionBumpError):
    """The PR guard found a violation."""


class TagError(VersionBumpError):
    """A tag exists on a different commit."""


class HookError(VersionBumpError):
    """An `after` hook or `verify` command failed."""
