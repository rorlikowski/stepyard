"""
Stepyard CLI package.

Re-exports the ``cli`` entry point for use in ``pyproject.toml`` scripts
and direct invocation.
"""

from stepyard.cli.app import cli

__all__ = ["cli"]
