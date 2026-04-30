"""全局样式构建器。"""
from __future__ import annotations

from .tokens import get_theme_tokens


def build_app_stylesheet(theme_name: str) -> str:
    """根据主题生成全局 QSS 字符串。"""
    t = get_theme_tokens(theme_name)
    return f"""
    QWidget {{
        background-color: {t.window_bg};
        color: {t.text_primary};
        font-size: {t.font_body}px;
    }}
    QMainWindow, QDialog {{
        background-color: {t.window_bg};
    }}
    QFrame[role="header-card"] {{
        background-color: {t.panel_bg};
        border: 1px solid {t.border};
        border-radius: {t.radius_lg}px;
    }}
    QLabel[role="app-title"] {{
        font-size: {t.font_headline}px;
        font-weight: 700;
        color: {t.text_primary};
    }}
    QLabel[role="secondary"] {{
        color: {t.text_secondary};
    }}
    QGroupBox {{
        background-color: {t.panel_bg};
        border: 1px solid {t.border};
        border-radius: {t.radius_lg}px;
        margin-top: 8px;
        font-weight: 600;
        padding-top: 2px;
    }}
    QGroupBox::title {{
        left: 10px;
        padding: 0 4px 0 4px;
        color: {t.text_secondary};
        background-color: {t.panel_bg};
    }}
    QLabel[role="section-title"] {{
        font-size: {t.font_title}px;
        font-weight: 700;
        color: {t.text_primary};
    }}
    QMenuBar, QMenu, QStatusBar {{
        background-color: {t.panel_bg};
        color: {t.text_primary};
    }}
    QPushButton {{
        background-color: {t.panel_bg};
        border: 1px solid {t.border};
        border-radius: {t.radius_sm}px;
        padding: 6px 10px;
        min-height: 30px;
        font-weight: 600;
    }}
    QPushButton[role="compact"] {{
        min-height: 22px;
        padding: 2px 8px;
        font-size: 11px;
    }}
    QPushButton:hover {{
        border-color: {t.primary};
    }}
    QPushButton[role="primary"] {{
        background-color: {t.primary};
        color: #FFFFFF;
        border-color: {t.primary};
        border-radius: {t.radius_md}px;
        min-height: 42px;
        font-size: {t.font_headline}px;
        font-weight: 700;
        padding: 10px 14px;
    }}
    QPushButton[role="primary"]:hover {{
        background-color: {t.primary_hover};
        border-color: {t.primary_hover};
    }}
    QPushButton[role="primary"]:pressed {{
        background-color: {t.primary_hover};
    }}
    QPushButton:disabled {{
        color: {t.text_secondary};
        border-color: {t.border};
    }}
    QLineEdit, QPlainTextEdit, QTextEdit, QListWidget, QTableWidget, QComboBox {{
        background-color: {t.panel_bg};
        border: 1px solid {t.border};
        border-radius: {t.radius_sm}px;
        padding: 4px 6px;
    }}
    QListWidget {{
        alternate-background-color: {t.panel_alt_bg};
    }}
    QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus {{
        border-color: {t.primary};
    }}
    QHeaderView::section {{
        background-color: {t.panel_alt_bg};
        color: {t.text_primary};
        border: 1px solid {t.border};
        font-weight: 600;
        padding: 6px;
    }}
    QTableWidget {{
        gridline-color: {t.border};
        alternate-background-color: {t.panel_alt_bg};
        selection-background-color: {t.primary};
        selection-color: #FFFFFF;
    }}
    QLabel[role="sync-pill"] {{
        border: 1px solid {t.border};
        border-radius: {t.radius_md}px;
        padding: 2px 8px;
        font-weight: 600;
        min-height: 18px;
    }}
    QLabel[syncState="synced"] {{
        color: {t.success};
    }}
    QLabel[syncState="behind"] {{
        color: {t.warning};
    }}
    QLabel[syncState="ahead"] {{
        color: {t.primary};
    }}
    QLabel[syncState="diverged"] {{
        color: {t.danger};
    }}
    QLabel[syncState="unknown"] {{
        color: {t.text_secondary};
    }}
    QListWidget::item {{
        border-radius: {t.radius_sm}px;
        padding: 6px;
    }}
    QListWidget#projectList::item {{
        border-bottom: 1px solid {t.border};
    }}
    QListWidget::item:selected {{
        background-color: {t.primary};
        color: #FFFFFF;
    }}
    QListWidget#projectList::item:hover {{
        border: 1px solid {t.primary};
    }}
    QLabel[role="success"], QPlainTextEdit[role="success"] {{
        color: {t.success};
    }}
    QLabel[role="danger"], QPlainTextEdit[role="danger"] {{
        color: {t.danger};
    }}
    """
