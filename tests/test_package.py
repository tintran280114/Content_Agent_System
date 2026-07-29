from __future__ import annotations

import unittest

import _bootstrap  # noqa: F401
import content_agent


class PackageTests(unittest.TestCase):
    def test_package_exposes_mvp_version(self) -> None:
        self.assertEqual(content_agent.__version__, "0.8.0")


if __name__ == "__main__":
    unittest.main()
