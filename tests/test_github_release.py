"""GitHub Release 解析与版本比较单元测试。"""
from __future__ import annotations

import unittest

from src.git_gui.utils.github_release import (
    _match_asset_urls,
    is_newer_version,
    parse_tag_version,
)


class GitHubReleaseParsingTest(unittest.TestCase):
    def test_parse_tag_version(self) -> None:
        self.assertEqual(str(parse_tag_version("v1.0.3")), "1.0.3")
        self.assertEqual(str(parse_tag_version("1.0.3-beta.1")), "1.0.3b1")

    def test_is_newer_version(self) -> None:
        self.assertTrue(is_newer_version("1.0.3", "1.0.2"))
        self.assertFalse(is_newer_version("1.0.2", "1.0.3"))
        self.assertTrue(is_newer_version("1.0.4-beta.1", "1.0.3"))

    def test_match_windows_setup_asset(self) -> None:
        assets = [
            {
                "name": "GitPullSwitchTool-Setup-1.0.3.exe",
                "browser_download_url": "https://example.com/setup.exe",
            },
            {
                "name": "GitPullSwitchTool-Windows-v1.0.3.zip",
                "browser_download_url": "https://example.com/portable.zip",
            },
        ]
        urls = _match_asset_urls("https://github.com/o/r/releases/v1.0.3", assets)
        self.assertEqual(urls.windows_installer_url, "https://example.com/setup.exe")
        self.assertIsNone(urls.macos_dmg_url)


if __name__ == "__main__":
    unittest.main()
