"""UI 图标映射。

优先使用 Qt 内置标准图标，避免额外资源依赖影响打包稳定性。
"""
from __future__ import annotations

from PySide6.QtWidgets import QStyle, QWidget
from PySide6.QtGui import QIcon


ICON_MAP = {
    "add": QStyle.SP_FileDialogNewFolder,
    "remove": QStyle.SP_TrashIcon,
    "clone": QStyle.SP_DialogOpenButton,
    "refresh": QStyle.SP_BrowserReload,
    "fetch": QStyle.SP_ArrowDown,
    "cleanup": QStyle.SP_DialogResetButton,
    "open": QStyle.SP_DirOpenIcon,
    "switch": QStyle.SP_MediaPlay,
    "favorite": QStyle.SP_DialogYesButton,
    "fill": QStyle.SP_ArrowRight,
    "console": QStyle.SP_ComputerIcon,
    "clear": QStyle.SP_DialogDiscardButton,
}


def get_icon(widget: QWidget, name: str) -> QIcon:
    """根据语义名称获取标准图标。"""
    pix = ICON_MAP.get(name)
    if pix is None:
        return QIcon()
    return widget.style().standardIcon(pix)
