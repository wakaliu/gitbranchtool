"""日志显示组件。

封装 QTextEdit，提供自动滚动、颜色高亮和清理功能。
"""
from PySide6.QtWidgets import QTextEdit
from PySide6.QtGui import QTextCursor, QColor
from PySide6.QtCore import Qt, Signal

class LogTextEdit(QTextEdit):
    """运行日志显示控件。

    为什么继承 QTextEdit 而非使用信号直接更新：便于在主窗口中统一管理样式和行为。
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setLineWrapMode(QTextEdit.WidgetWidth)
        self.document().setMaximumBlockCount(800)  # 防止内存无限增长

        # 基础样式
        self.setStyleSheet("""
            QTextEdit {
                background-color: #f8f9fa;
                font-family: 'Consolas', 'Courier New', monospace;
                font-size: 13px;
                border: 1px solid #e0e0e0;
            }
        """)

    def append_log(self, text: str) -> None:
        """追加日志，支持简单颜色区分 (success/green, error/red)。"""
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.End)

        if "成功" in text or "完成" in text or "耗时" in text:
            cursor.insertHtml(f'<span style="color: #28a745;">{text}</span><br>')
        elif "失败" in text or "错误" in text or "超时" in text:
            cursor.insertHtml(f'<span style="color: #dc3545;">{text}</span><br>')
        else:
            cursor.insertHtml(f'{text}<br>')

        self.setTextCursor(cursor)
        self.ensureCursorVisible()

    def clear_logs(self) -> None:
        self.clear()
