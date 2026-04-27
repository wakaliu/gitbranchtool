"""GitHub Issues 反馈提交工具。

使用 GitHub REST API 提交带截图的反馈。
"""
import requests
from pathlib import Path
from typing import Optional
from ..config.settings import Settings

class GitHubIssueReporter:
    """反馈提交器。

    为什么使用 requests + token：简单可靠，支持附件图片。
    token 建议用户在设置中配置 (不提交到代码仓库)。
    """
    def __init__(self):
        self.settings = Settings()
        self.token = None  # 从设置或环境变量加载

    def submit_feedback(self, title: str, body: str, image_paths: list[Path] = None) -> bool:
        """提交 Issue 到 GitHub。

        当前仓库地址从 config.yaml 读取。
        """
        repo = self.settings.get("github.repo", "your-username/git-gui-pull-switch-tool")
        url = f"https://api.github.com/repos/{repo}/issues"

        headers = {
            "Accept": "application/vnd.github.v3+json",
        }
        if self.token:
            headers["Authorization"] = f"token {self.token}"

        issue_data = {
            "title": title or "用户反馈 - Git拉线切线工具",
            "body": body or "无详细描述",
            "labels": ["feedback"]
        }

        try:
            response = requests.post(url, json=issue_data, headers=headers, timeout=15)
            if response.status_code in (201, 200):
                # TODO: 后续支持上传图片作为 comment
                return True
            return False
        except Exception:
            return False

    def set_token(self, token: str) -> None:
        self.token = token
