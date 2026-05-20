"""应用更新相关界面文案（中/英）。"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class UpdateTextBundle:
    """某一语言下的更新 UI 字符串集合。"""

    menu_check_updates: str
    status_checking: str
    msg_latest_title: str
    msg_latest_body: str
    msg_check_failed_title: str
    dialog_title: str
    dialog_intro: str
    label_current: str
    label_new: str
    notes_placeholder: str
    btn_update: str
    btn_later: str
    btn_close: str
    progress_title: str
    progress_label: str
    progress_downloading: str
    msg_download_failed_title: str
    msg_install_failed_title: str
    msg_install_launch_body: str


_TEXTS: dict[str, UpdateTextBundle] = {
    "zh": UpdateTextBundle(
        menu_check_updates="检查更新...",
        status_checking="正在检查更新...",
        msg_latest_title="检查更新",
        msg_latest_body="当前已是最新版本。",
        msg_check_failed_title="无法检查更新",
        dialog_title="发现新版本",
        dialog_intro="有新版本可安装，是否立即更新？",
        label_current="当前版本：{current}",
        label_new="最新版本：{new}",
        notes_placeholder="（暂无 Release 说明）",
        btn_update="立即更新",
        btn_later="暂不更新",
        btn_close="关闭",
        progress_title="正在下载更新",
        progress_label="正在下载安装包，请稍候...",
        progress_downloading="已下载 {done_mb:.1f} / {total_mb:.1f} MB",
        msg_download_failed_title="下载失败",
        msg_install_failed_title="无法启动安装",
        msg_install_launch_body="已安排退出并安装更新；若未自动完成，请手动运行下载的安装包。",
    ),
    "en": UpdateTextBundle(
        menu_check_updates="Check for Updates...",
        status_checking="Checking for updates...",
        msg_latest_title="Check for Updates",
        msg_latest_body="You are on the latest version.",
        msg_check_failed_title="Update Check Failed",
        dialog_title="Update Available",
        dialog_intro="A new version is available. Install now?",
        label_current="Current: {current}",
        label_new="Latest: {new}",
        notes_placeholder="(No release notes)",
        btn_update="Update Now",
        btn_later="Not Now",
        btn_close="Close",
        progress_title="Downloading Update",
        progress_label="Downloading installer, please wait...",
        progress_downloading="Downloaded {done_mb:.1f} / {total_mb:.1f} MB",
        msg_download_failed_title="Download Failed",
        msg_install_failed_title="Could Not Start Installer",
        msg_install_launch_body=(
            "The app will quit to apply the update. "
            "If nothing happens, run the downloaded installer manually."
        ),
    ),
}


def get_update_texts(language: str) -> UpdateTextBundle:
    """返回指定语言的文案包，未知语言回退中文。"""
    return _TEXTS.get(language, _TEXTS["zh"])
