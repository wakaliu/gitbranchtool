"""进度对话框。

用于长时间 Git 操作，提供取消功能和进度反馈。
"""
from PySide6.QtWidgets import QProgressDialog, QLabel, QVBoxLayout, QWidget
from PySide6.QtCore import Qt

class OperationProgressDialog(QProgressDialog):
    """Git 操作进度对话框。

    关闭 Qt 默认的 autoClose/autoReset：进度到最大值时若自动关窗，业务代码再在
    on_done 里 close() 可能对同一 C++ 对象二次收尾，易在切线完成瞬间闪退。
    结束时机一律由 MainWindow 在汇总后显式 close。
    """
    def __init__(self, parent=None, title: str = "正在执行"):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumDuration(300)  # 避免闪现
        self.setRange(0, 100)
        self.setValue(0)
        self.setAutoClose(False)
        self.setAutoReset(False)
        self.setCancelButtonText("取消")
        self.setLabelText("正在处理 Git 操作，请稍候...")

        # 自定义标签显示更多信息
        self.info_label = QLabel("初始化...")
        self.info_label.setWordWrap(True)
        layout = self.layout()
        if isinstance(layout, QVBoxLayout):
            layout.insertWidget(1, self.info_label)

    def update_status(self, message: str) -> None:
        self.info_label.setText(message)

    def update_progress(self, completed: int, total: int, message: str = "") -> None:
        """更新确定性进度。"""
        if total <= 0:
            self.setRange(0, 0)
            if message:
                self.update_status(message)
            return
        self.setRange(0, total)
        self.setValue(min(completed, total))
        if message:
            self.update_status(message)

    def close(self) -> None:
        super().close()
