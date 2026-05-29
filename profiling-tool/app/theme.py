BG_BASE    = "#0d0d0d"
BG_PANEL   = "#1a1a1a"
BG_SURFACE = "#252525"
BG_ELEVATED= "#333333"
BORDER     = "#404040"

TEXT        = "#e8e8e8"
TEXT_MUTED  = "#a0a0a0"
TEXT_SUBTLE = "#707070"

ACCENT_ON   = "#4a9eff"
ACCENT_OFF  = "#606060"
SUCCESS     = "#4ade80"
WARNING     = "#facc15"
ERROR       = "#f87171"

LANG_COLORS: dict[str, str] = {
    "java":   "#4a9eff",
    "python": "#4a9eff",
    "go":     "#4a9eff",
}

PANEL_WIDTH = 300

APP_STYLE = f"""
* {{
    font-family: -apple-system, "Segoe UI", "Noto Sans", sans-serif;
    font-size: 13px;
}}
QMainWindow, QWidget {{
    background-color: {BG_BASE};
    color: {TEXT};
}}
QScrollArea {{ border: none; }}
QListWidget {{
    background: transparent;
    border: none;
}}
QListWidget::item {{
    background: transparent;
    border: none;
    padding: 0;
}}
QScrollBar:vertical {{
    background: transparent;
    width: 8px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {BG_ELEVATED};
    border: none;
    min-height: 24px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}
QSplitter::handle:vertical {{
    background: {BORDER};
    height: 1px;
}}
QToolTip {{
    background-color: {BG_SURFACE};
    color: {TEXT};
    border: 1px solid {BORDER};
    padding: 4px 8px;
}}
"""
