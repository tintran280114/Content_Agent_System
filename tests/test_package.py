"""Smoke tests for the top-level package."""

import content_agent


def test_package_import() -> None:
    """The package can be imported and exposes its bootstrap version."""
    assert content_agent.__version__ == "0.1.0"
