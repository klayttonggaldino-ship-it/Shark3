"""Tema escuro: fundo #1e1e1e, destaque rosa #ff4d8d (conforme a especificação)."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPalette, QPen, QPixmap
from PySide6.QtWidgets import QApplication

from .paths import UI_DIR

BG = "#1e1e1e"
SURFACE = "#252526"
SURFACE2 = "#2d2d30"
BORDER = "#3a3a3d"
TEXT = "#e6e6e6"
MUTED = "#9a9a9a"
ACCENT = "#ff4d8d"
ACCENT_HOVER = "#ff6a9f"

QSS = """
* { font-family: "Segoe UI", "Inter", "Noto Sans", sans-serif; color: @TEXT@; }
QWidget { background: @BG@; font-size: 10pt; }
QLabel, QCheckBox, QRadioButton { background: transparent; }
QLabel#muted, QLabel#hint { color: @MUTED@; }
QLabel#hint { font-size: 9pt; }
QLabel#title { font-size: 13pt; font-weight: 600; }
QLabel#emptyIcon { font-size: 64pt; color: #34343a; }
QLabel#emptyText { color: @MUTED@; font-size: 11pt; }

QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit {
    background: @SURFACE@; border: 1px solid @BORDER@; border-radius: 10px; padding: 7px 12px;
    selection-background-color: @ACCENT@; selection-color: white;
}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus, QPlainTextEdit:focus { border-color: @ACCENT@; }
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled { color: #6b6b6b; }
QPlainTextEdit { font-family: "Cascadia Mono", "Consolas", monospace; font-size: 9pt; border-radius: 12px; }

QComboBox { padding-right: 28px; }
QComboBox::drop-down { border: none; width: 26px; }
QComboBox::down-arrow { image: url(@ARROW_DOWN@); width: 12px; height: 12px; }
QComboBox QAbstractItemView {
    background: @SURFACE@; border: 1px solid @BORDER@; selection-background-color: #33333a;
    outline: 0; padding: 4px;
}
QSpinBox::up-button, QDoubleSpinBox::up-button { subcontrol-origin: border; subcontrol-position: top right; width: 20px; border: none; background: transparent; }
QSpinBox::down-button, QDoubleSpinBox::down-button { subcontrol-origin: border; subcontrol-position: bottom right; width: 20px; border: none; background: transparent; }
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow { image: url(@ARROW_UP@); width: 10px; height: 10px; }
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow { image: url(@ARROW_DOWN@); width: 10px; height: 10px; }

QPushButton {
    background: @SURFACE2@; border: 1px solid @BORDER@; border-radius: 10px; padding: 7px 14px;
}
QPushButton:hover { background: #36363a; }
QPushButton:pressed { background: #404045; }
QPushButton:disabled { color: #6b6b6b; background: #232325; }
QPushButton#primary { background: @ACCENT@; border: none; color: white; font-weight: 600; padding: 8px 20px; }
QPushButton#primary:hover { background: @ACCENT_HOVER@; }
QPushButton#primary:disabled { background: #5a2b3d; color: #b98a9b; }
QPushButton#ghost { background: transparent; border: none; color: #c8c8c8; padding: 6px 10px; }
QPushButton#ghost:hover { background: #2a2a2e; }
QPushButton#ghost:disabled { color: #5d5d5d; }
QToolButton { background: transparent; border: none; border-radius: 10px; padding: 6px 9px; font-size: 13pt; }
QToolButton:hover { background: #2a2a2e; }

QCheckBox, QRadioButton { spacing: 8px; }
QCheckBox::indicator { width: 17px; height: 17px; border-radius: 5px; border: 1px solid #55555a; background: @SURFACE@; }
QCheckBox::indicator:hover { border-color: @ACCENT@; }
QCheckBox::indicator:checked { background: @ACCENT@; border-color: @ACCENT@; image: url(@CHECK@); }
QTreeView::indicator { width: 17px; height: 17px; border-radius: 5px; border: 1px solid #55555a; background: @SURFACE@; }
QTreeView::indicator:checked { background: @ACCENT@; border-color: @ACCENT@; image: url(@CHECK@); }

QTabWidget::pane { border: none; top: -1px; }
QTabBar { background: transparent; }
QTabBar::tab { background: transparent; color: @MUTED@; padding: 8px 18px; margin-right: 4px; border-radius: 10px; }
QTabBar::tab:selected { background: @SURFACE2@; color: @TEXT@; }
QTabBar::tab:hover:!selected { color: @TEXT@; }

QTreeWidget, QTreeView, QListWidget { background: @BG@; border: none; outline: 0; }
QTreeView::item, QListWidget::item { border: none; }
QTreeView { selection-background-color: #2c2c33; }
QTreeView::branch { background: transparent; }
QTreeView::branch:selected { background: #2c2c33; }
QTreeView::branch:hover { background: #252529; }
QHeaderView::section {
    background: @BG@; color: @MUTED@; border: none; border-bottom: 1px solid #2f2f32; padding: 7px 8px;
}
QListWidget#nav { background: #1a1a1b; border-right: 1px solid #2f2f32; padding: 8px; }
QListWidget#nav::item { padding: 10px 12px; border-radius: 9px; margin-bottom: 2px; color: #c8c8c8; }
QListWidget#nav::item:selected { background: @SURFACE2@; color: white; }
QListWidget#nav::item:hover:!selected { background: #242426; }

QScrollArea { border: none; background: transparent; }
QScrollBar:vertical { width: 10px; background: transparent; margin: 2px; }
QScrollBar::handle:vertical { background: #3c3c40; border-radius: 4px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: #55555a; }
QScrollBar:horizontal { height: 10px; background: transparent; margin: 2px; }
QScrollBar::handle:horizontal { background: #3c3c40; border-radius: 4px; min-width: 30px; }
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page { background: none; border: none; width: 0; height: 0; }

QProgressBar { background: @SURFACE2@; border: none; border-radius: 3px; max-height: 6px; text-align: center; color: transparent; }
QProgressBar::chunk { background: @ACCENT@; border-radius: 3px; }

QMenu { background: @SURFACE@; border: 1px solid @BORDER@; padding: 6px; border-radius: 10px; }
QMenu::item { padding: 7px 24px; border-radius: 6px; }
QMenu::item:selected { background: #33333a; }
QMenu::separator { height: 1px; background: #38383c; margin: 5px 8px; }
QToolTip { background: @SURFACE2@; color: @TEXT@; border: 1px solid @BORDER@; padding: 6px; }
QStatusBar { background: #181819; }
QStatusBar QLabel { color: @MUTED@; font-size: 9pt; }
QStatusBar::item { border: none; }
QMessageBox, QDialog { background: @BG@; }
QGroupBox { border: 1px solid #2f2f32; border-radius: 12px; margin-top: 14px; padding: 14px 12px 10px 12px; }
QGroupBox::title { subcontrol-origin: margin; left: 14px; padding: 0 6px; color: @MUTED@; }
"""


def ensure_icons() -> dict[str, str]:
    """Gera os pequenos ícones (check/setas) usados pelo QSS."""
    UI_DIR.mkdir(parents=True, exist_ok=True)

    def make(name: str, points: list[tuple[float, float]], color: str, width: float) -> str:
        pm = QPixmap(16, 16)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor(color), width)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        path = QPainterPath()
        path.moveTo(*points[0])
        for pt in points[1:]:
            path.lineTo(*pt)
        p.drawPath(path)
        p.end()
        path_str = UI_DIR / name
        pm.save(str(path_str), "PNG")
        return path_str.as_posix()

    return {
        "CHECK": make("check.png", [(4, 8.5), (7, 11.5), (12, 5)], "#ffffff", 2.2),
        "ARROW_DOWN": make("arrow_down.png", [(4, 6), (8, 10), (12, 6)], MUTED, 1.8),
        "ARROW_UP": make("arrow_up.png", [(4, 10), (8, 6), (12, 10)], MUTED, 1.8),
    }


def install(app: QApplication) -> None:
    app.setStyle("Fusion")
    font = QFont("Segoe UI", 10)
    font.setStyleHint(QFont.StyleHint.SansSerif)
    app.setFont(font)
    pal = QPalette()
    for role, color in {
        QPalette.ColorRole.Window: BG, QPalette.ColorRole.WindowText: TEXT, QPalette.ColorRole.Base: SURFACE,
        QPalette.ColorRole.AlternateBase: SURFACE2, QPalette.ColorRole.Text: TEXT, QPalette.ColorRole.Button: SURFACE2,
        QPalette.ColorRole.ButtonText: TEXT, QPalette.ColorRole.Highlight: ACCENT,
        QPalette.ColorRole.HighlightedText: "#ffffff", QPalette.ColorRole.ToolTipBase: SURFACE2,
        QPalette.ColorRole.ToolTipText: TEXT, QPalette.ColorRole.PlaceholderText: "#7a7a7a",
    }.items():
        pal.setColor(role, QColor(color))
    app.setPalette(pal)
    qss = QSS
    tokens = {"BG": BG, "SURFACE": SURFACE, "SURFACE2": SURFACE2, "BORDER": BORDER, "TEXT": TEXT, "MUTED": MUTED,
              "ACCENT": ACCENT, "ACCENT_HOVER": ACCENT_HOVER, **ensure_icons()}
    for key, val in tokens.items():
        qss = qss.replace(f"@{key}@", val)
    app.setStyleSheet(qss)
