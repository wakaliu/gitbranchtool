"""应用更新相关界面文案（中/英）。"""
from __future__ import annotations

from dataclasses import dataclass

from ...core.update.check_messages import UpdateCheckFailureText, format_update_check_failure

__all__ = ["UpdateTextBundle", "UpdateCheckFailureText", "format_update_check_failure", "get_update_texts"]


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
    phase_download: str
    phase_install: str
    progress_downloading: str
    progress_download_percent: str
    log_check_start: str
    log_skip_startup_cooldown: str
    log_skip_rate_limit_backoff: str
    log_download_start: str
    log_download_done: str
    log_install_start: str
    log_install_background: str
    log_install_quit: str
    msg_install_background: str
    install_background_detail: str
    log_cancelled: str
    msg_download_failed_title: str
    msg_cancelled_title: str
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
        progress_title="正在更新",
        progress_label="正在下载安装包，请稍候...",
        phase_download="下载进度",
        phase_install="安装进度",
        progress_downloading="已下载 {done_mb:.1f} / {total_mb:.1f} MB",
        progress_download_percent="下载进度：{percent}%",
        log_check_start="开始检查更新...",
        log_skip_startup_cooldown=(
            "跳过启动自动检查：冷却 {cooldown} 分钟，约 {remain} 后可再试"
            "（仅限制连续启动时的自动检查，手动「检查更新」不受影响）"
        ),
        log_skip_rate_limit_backoff="跳过检查更新：GitHub API 限流退避中，{when}",
        log_download_start="开始下载更新包：{name}",
        log_download_done="更新包下载完成：{path}",
        log_install_start="正在退出并启动安装程序...",
        log_install_background="正在后台安装更新，安装完成后将自动重新打开程序",
        log_install_quit="应用即将退出，请在后台完成安装",
        msg_install_background=(
            "正在后台安装更新，请稍候。\n\n"
            "本窗口将自动关闭；安装完成后将自动重新打开程序。"
        ),
        install_background_detail=(
            "正在后台安装更新，请稍候…\n"
            "安装完成后将自动重新打开程序。"
        ),
        log_cancelled="用户已取消更新",
        msg_download_failed_title="下载失败",
        msg_cancelled_title="更新已取消",
        msg_install_failed_title="无法启动安装",
        msg_install_launch_body="将退出并在后台完成安装，完成后自动重新打开程序。",
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
        progress_title="Updating",
        progress_label="Downloading installer, please wait...",
        phase_download="Download",
        phase_install="Install",
        progress_downloading="Downloaded {done_mb:.1f} / {total_mb:.1f} MB",
        progress_download_percent="Download: {percent}%",
        log_check_start="Checking for updates...",
        log_skip_startup_cooldown=(
            "Skipped startup check: {cooldown} min cooldown, retry in about {remain} "
            "(manual Check for Updates is not affected)"
        ),
        log_skip_rate_limit_backoff=(
            "Skipped update check: GitHub rate-limit backoff active until {when}"
        ),
        log_download_start="Downloading update: {name}",
        log_download_done="Download complete: {path}",
        log_install_start="Quitting to run installer...",
        log_install_background=(
            "Installing update in the background; the app will reopen when done"
        ),
        log_install_quit="Application will exit; installation continues in the background",
        msg_install_background=(
            "Installing the update in the background. Please wait.\n\n"
            "This window will close automatically. The app will reopen when installation finishes."
        ),
        install_background_detail=(
            "Installing in the background. Please wait…\n"
            "The app will reopen automatically when done."
        ),
        log_cancelled="Update cancelled by user",
        msg_download_failed_title="Download Failed",
        msg_cancelled_title="Update Cancelled",
        msg_install_failed_title="Could Not Start Installer",
        msg_install_launch_body=(
            "The app will quit to finish installation in the background and then reopen."
        ),
    ),
}


def get_update_texts(language: str) -> UpdateTextBundle:
    """返回指定语言的文案包，未知语言回退中文。"""
    return _TEXTS.get(language, _TEXTS["zh"])
