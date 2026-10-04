"""version-bump-bot: post-merge semantic-version bumps driven by .github/version-bump.toml."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("version-bump-bot")
except PackageNotFoundError:  # running from a plain source checkout
    __version__ = "0.0.0"
