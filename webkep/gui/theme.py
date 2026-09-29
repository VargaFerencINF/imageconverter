"""Sötét / világos téma: paletta, stíluslap és színezhető vektoros ikonok."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QByteArray, QDir, QRectF, QSize, Qt, QTemporaryDir
from PySide6.QtGui import QColor, QIcon, QPainter, QPalette, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication


@dataclass(frozen=True)
class Palette:
    name: str
    bg: str
    surface: str
    surface2: str
    border: str
    text: str
    muted: str
    accent: str
    accent_hover: str
    accent_pressed: str
    success: str
    warning: str
    danger: str
    selection: str


DARK = Palette(
    name="dark",
    bg="#121419",
    surface="#1a1d24",
    surface2="#232733",
    border="#2e3440",
    text="#e7e9ee",
    muted="#949cab",
    accent="#5b8cff",
    accent_hover="#7aa2ff",
    accent_pressed="#4674e6",
    success="#3dd68c",
    warning="#f5b94a",
    danger="#ff6b6b",
    selection="#2b3b63",
)

LIGHT = Palette(
    name="light",
    bg="#f2f4f8",
    surface="#ffffff",
    surface2="#f6f7fa",
    border="#d8dde6",
    text="#1a1f2b",
    muted="#5f6878",
    accent="#3f6fe8",
    accent_hover="#5883f0",
    accent_pressed="#325dd0",
    success="#1c9a5f",
    warning="#b97d06",
    danger="#d9463b",
    selection="#d6e2ff",
)

_current: Palette = DARK
_asset_dir: QTemporaryDir | None = None


def current() -> Palette:
    return _current


def resource_path(relative: str) -> Path:
    """Fájl elérése fejlesztéskor és a PyInstaller által csomagolt exe-ben is."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    return base / relative


# --------------------------------------------------------------------------
# Ikonok (24×24-es, vonalas SVG-k; a szín futásidőben kerül bele)
# --------------------------------------------------------------------------

_ICONS: dict[str, str] = {
    "folder": '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    "folder_out": '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>'
    '<path d="M10 13h6M13.5 10.5 16 13l-2.5 2.5"/>',
    "play": '<path d="M7 5l12 7-12 7z" fill="currentColor"/>',
    "pause": '<rect x="6" y="5" width="4" height="14" rx="1" fill="currentColor"/>'
    '<rect x="14" y="5" width="4" height="14" rx="1" fill="currentColor"/>',
    "stop": '<rect x="6" y="6" width="12" height="12" rx="2" fill="currentColor"/>',
    "eye": '<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
    "refresh": '<path d="M20 11a8 8 0 0 0-14.9-3M4 4v4h4"/><path d="M4 13a8 8 0 0 0 14.9 3M20 20v-4h-4"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "trash": '<path d="M4 7h16M10 11v6M14 11v6M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12M9 7V4h6v3"/>',
    "download": '<path d="M12 4v11M7 10l5 5 5-5M5 20h14"/>',
    "external": '<path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/>',
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7.5v.5"/>',
    "sun": '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4'
    'M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
    "moon": '<path d="M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z"/>',
    "save": '<path d="M5 4h11l3 3v12a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1z"/><path d="M8 4v5h7V4M8 20v-6h8v6"/>',
    "gauge": '<path d="M4 18a8 8 0 1 1 16 0"/><path d="M12 18l4-6"/>',
    "zoom_in": '<circle cx="11" cy="11" r="7"/><path d="M21 21l-5-5M11 8v6M8 11h6"/>',
    "zoom_out": '<circle cx="11" cy="11" r="7"/><path d="M21 21l-5-5M8 11h6"/>',
    "fit": '<path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/>',
    "one": '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M10 9l2-1.5V16"/>',
    "image": '<rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="9" cy="10" r="2"/><path d="M21 16l-5-5-9 9"/>',
    "chevron_down": '<path d="M6 9l6 6 6-6"/>',
    "chevron_up": '<path d="M6 15l6-6 6 6"/>',
    "chevron_left": '<path d="M15 6l-6 6 6 6"/>',
    "chevron_right": '<path d="M9 6l6 6-6 6"/>',
    "check": '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
    "x": '<path d="M6 6l12 12M18 6L6 18"/>',
    "list": '<path d="M9 6h11M9 12h11M9 18h11M4 6h.01M4 12h.01M4 18h.01"/>',
    "sliders": '<path d="M4 6h9M17 6h3M4 12h3M11 12h9M4 18h11M19 18h1"/>'
    '<circle cx="15" cy="6" r="2"/><circle cx="9" cy="12" r="2"/><circle cx="17" cy="18" r="2"/>',
    "globe": '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18"/>',
    "files": '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/>',
    "check_all": '<rect x="3" y="3" width="18" height="18" rx="3"/><path d="M8 12l3 3 5-6"/>',
    "square": '<rect x="3" y="3" width="18" height="18" rx="3"/>',
}

_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{c}" '
    'stroke-width="{w}" stroke-linecap="round" stroke-linejoin="round">{body}</svg>'
)


def _svg(name: str, color: str, stroke: float = 2.0) -> bytes:
    body = _ICONS[name].replace("currentColor", color)
    return _SVG.format(c=color, w=stroke, body=body).encode()


def render_svg(svg: bytes, size: int, dpr: float = 2.0) -> QPixmap:
    pm = QPixmap(int(size * dpr), int(size * dpr))
    pm.fill(Qt.GlobalColor.transparent)
    renderer = QSvgRenderer(QByteArray(svg))
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter, QRectF(0, 0, pm.width(), pm.height()))
    painter.end()
    pm.setDevicePixelRatio(dpr)
    return pm


def icon(name: str, role: str = "text", size: int = 18) -> QIcon:
    """Témához igazított ikon; ``role``: text, muted, accent, white, success, warning, danger."""
    p = _current
    color = {
        "text": p.text,
        "muted": p.muted,
        "accent": p.accent,
        "white": "#ffffff",
        "success": p.success,
        "warning": p.warning,
        "danger": p.danger,
    }.get(role, role)
    ic = QIcon()
    for s in (size, size * 2):
        ic.addPixmap(render_svg(_svg(name, color), s, 1.0), QIcon.Mode.Normal)
        ic.addPixmap(render_svg(_svg(name, p.muted if role != "white" else "#dfe6ff"), s, 1.0), QIcon.Mode.Disabled)
    return ic


LOGO_SVG = b"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
<stop offset="0" stop-color="#4f7cff"/><stop offset="1" stop-color="#9b5cff"/></linearGradient></defs>
<rect x="2" y="2" width="60" height="60" rx="14" fill="url(#g)"/>
<circle cx="23" cy="23" r="6" fill="#ffffff" fill-opacity="0.95"/>
<path d="M10 50 L26 32 L36 42 L44 34 L54 50 Z" fill="#ffffff" fill-opacity="0.95"/>
</svg>"""


def app_icon() -> QIcon:
    ico = resource_path("assets/icon.ico")
    png = resource_path("assets/icon.png")
    if png.exists():
        return QIcon(str(png))
    if ico.exists():
        return QIcon(str(ico))
    ic = QIcon()
    for s in (16, 24, 32, 48, 64, 128, 256):
        ic.addPixmap(render_svg(LOGO_SVG, s, 1.0))
    return ic


def logo_pixmap(size: int) -> QPixmap:
    return render_svg(LOGO_SVG, size, 2.0)


# --------------------------------------------------------------------------
# Stíluslap
# --------------------------------------------------------------------------


def _write_assets(p: Palette) -> Path:
    """A stíluslapban hivatkozott nyíl/pipa képek generálása ideiglenes mappába."""
    global _asset_dir
    if _asset_dir is None:
        # ASCII sablon: az alkalmazásnév (ékezet, szóköz) ne kerüljön az útvonalba
        _asset_dir = QTemporaryDir(QDir.tempPath() + "/webkep-theme-XXXXXX")
    base = Path(_asset_dir.path())
    for name, color, tag in (
        ("chevron_down", p.muted, "down"),
        ("chevron_up", p.muted, "up"),
        ("check", "#ffffff", "check"),
    ):
        svg = _svg(name, color, 2.6)
        render_svg(svg, 12, 1.0).save(str(base / f"{tag}_{p.name}.png"))
        render_svg(svg, 24, 1.0).save(str(base / f"{tag}_{p.name}@2x.png"))
    return base


def stylesheet(p: Palette) -> str:
    assets = _write_assets(p).as_posix()

    def url(name: str) -> str:
        # idézőjelek: a felhasználói mappa neve tartalmazhat szóközt / ékezetet
        return 'url("' + f"{assets}/{name}_{p.name}.png".replace('"', '\\"') + '")'

    down, up, check = url("down"), url("up"), url("check")
    return f"""
* {{ outline: none; }}
QWidget {{ color: {p.text}; font-size: 10pt; }}
QMainWindow, QDialog, QWidget#Root {{ background: {p.bg}; }}
QToolTip {{ background: {p.surface2}; color: {p.text}; border: 1px solid {p.border};
    border-radius: 6px; padding: 6px 8px; }}

QFrame#Card {{ background: {p.surface}; border: 1px solid {p.border}; border-radius: 12px; }}
QFrame#Card QLabel, QFrame#Card QCheckBox, QFrame#Card QRadioButton {{ background: transparent; }}
QLabel#CardTitle {{ font-size: 10.5pt; font-weight: 600; }}
QLabel#Muted, QLabel#Hint {{ color: {p.muted}; }}
QLabel#Hint {{ font-size: 9pt; }}
QLabel#AppTitle {{ font-size: 15pt; font-weight: 700; }}
QLabel#Version {{ color: {p.muted}; font-size: 9pt; }}
QLabel#BigStat {{ font-size: 16pt; font-weight: 700; }}
QLabel#Badge {{ background: {p.surface2}; border: 1px solid {p.border}; border-radius: 9px;
    padding: 1px 8px; color: {p.muted}; font-size: 9pt; }}
QLabel#Success {{ color: {p.success}; font-weight: 600; }}
QLabel#Warning {{ color: {p.warning}; font-weight: 600; }}
QLabel#Danger {{ color: {p.danger}; font-weight: 600; }}
QLabel#DropHint {{ color: {p.muted}; font-size: 11pt; }}

QPushButton, QToolButton {{ background: {p.surface2}; border: 1px solid {p.border};
    border-radius: 8px; padding: 6px 12px; }}
QToolButton {{ padding: 5px; }}
QPushButton:hover, QToolButton:hover {{ border-color: {p.accent}; }}
QPushButton:pressed, QToolButton:pressed {{ background: {p.border}; }}
QPushButton:disabled, QToolButton:disabled {{ color: {p.muted}; border-color: {p.border}; }}
QPushButton:checked, QToolButton:checked {{ background: {p.selection}; border-color: {p.accent}; }}
QPushButton#Primary {{ background: {p.accent}; color: #ffffff; border: 1px solid {p.accent};
    font-weight: 600; padding: 8px 20px; }}
QPushButton#Primary:hover {{ background: {p.accent_hover}; border-color: {p.accent_hover}; }}
QPushButton#Primary:pressed {{ background: {p.accent_pressed}; }}
QPushButton#Primary:disabled {{ background: {p.border}; border-color: {p.border}; color: {p.muted}; }}
QPushButton#Danger:hover {{ border-color: {p.danger}; color: {p.danger}; }}
QToolButton::menu-indicator {{ image: none; width: 0; }}
QPushButton::menu-indicator {{ image: {down}; subcontrol-position: right center; right: 6px; }}

QLineEdit, QSpinBox, QComboBox, QPlainTextEdit, QTextBrowser {{ background: {p.surface2};
    border: 1px solid {p.border}; border-radius: 7px; padding: 5px 8px;
    selection-background-color: {p.accent}; selection-color: #ffffff; }}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus, QPlainTextEdit:focus {{ border-color: {p.accent}; }}
QLineEdit:disabled, QSpinBox:disabled, QComboBox:disabled {{ color: {p.muted}; }}
QPlainTextEdit#Log {{ font-family: "Cascadia Mono", "Consolas", "DejaVu Sans Mono", monospace; font-size: 9pt; }}
QSpinBox {{ padding-right: 22px; min-height: 20px; }}
QSpinBox::up-button, QSpinBox::down-button {{ subcontrol-origin: border; width: 20px; border: none;
    background: transparent; }}
QSpinBox::up-button {{ subcontrol-position: top right; }}
QSpinBox::down-button {{ subcontrol-position: bottom right; }}
QSpinBox::up-arrow {{ image: {up}; width: 10px; height: 10px; }}
QSpinBox::down-arrow {{ image: {down}; width: 10px; height: 10px; }}
QComboBox {{ padding-right: 26px; min-height: 20px; }}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox::down-arrow {{ image: {down}; width: 12px; height: 12px; }}
QComboBox QAbstractItemView {{ background: {p.surface}; border: 1px solid {p.border};
    selection-background-color: {p.selection}; selection-color: {p.text}; padding: 4px; outline: none; }}

QCheckBox, QRadioButton {{ spacing: 8px; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 5px; border: 1px solid {p.border};
    background: {p.surface2}; }}
QCheckBox::indicator:hover {{ border-color: {p.accent}; }}
QCheckBox::indicator:checked {{ background: {p.accent}; border-color: {p.accent}; image: {check}; }}
QCheckBox::indicator:disabled {{ background: {p.border}; }}
QCheckBox:disabled, QRadioButton:disabled {{ color: {p.muted}; }}

QSlider::groove:horizontal {{ height: 6px; background: {p.border}; border-radius: 3px; }}
QSlider::sub-page:horizontal {{ background: {p.accent}; border-radius: 3px; }}
QSlider::sub-page:horizontal:disabled {{ background: {p.muted}; }}
QSlider::handle:horizontal {{ background: #ffffff; border: 2px solid {p.accent}; width: 14px; height: 14px;
    margin: -6px 0; border-radius: 9px; }}
QSlider::handle:horizontal:hover {{ border-color: {p.accent_hover}; }}
QSlider::handle:horizontal:disabled {{ border-color: {p.muted}; }}

QTabWidget::pane {{ border: 1px solid {p.border}; border-radius: 10px; background: {p.surface}; top: -1px; }}
QTabBar::tab {{ background: transparent; color: {p.muted}; padding: 7px 12px; margin-right: 2px;
    border: 1px solid transparent; border-top-left-radius: 8px; border-top-right-radius: 8px; }}
QTabBar::tab:selected {{ background: {p.surface}; color: {p.text}; border-color: {p.border};
    border-bottom-color: {p.surface}; }}
QTabBar::tab:hover:!selected {{ color: {p.text}; }}

QTableView {{ background: {p.surface}; alternate-background-color: {p.surface2}; border: none;
    gridline-color: transparent; selection-background-color: {p.selection}; selection-color: {p.text}; }}
QTableView::item {{ padding: 0 6px; border: none; }}
QTableView::indicator {{ width: 15px; height: 15px; border-radius: 4px; border: 1px solid {p.border};
    background: {p.surface2}; }}
QTableView::indicator:checked {{ background: {p.accent}; border-color: {p.accent}; image: {check}; }}
QHeaderView {{ background: {p.surface}; border: none; }}
QHeaderView::section {{ background: {p.surface}; color: {p.muted}; border: none;
    border-bottom: 1px solid {p.border}; padding: 6px 8px; font-weight: 600; }}
QHeaderView::section:hover {{ color: {p.text}; }}
QTableCornerButton::section {{ background: {p.surface}; border: none; }}

QProgressBar {{ background: {p.surface2}; border: 1px solid {p.border}; border-radius: 8px;
    text-align: center; min-height: 20px; color: {p.text}; font-weight: 600; }}
QProgressBar::chunk {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {p.accent}, stop:1 #9b5cff);
    border-radius: 7px; }}

QScrollBar:vertical {{ background: transparent; width: 11px; margin: 2px; }}
QScrollBar:horizontal {{ background: transparent; height: 11px; margin: 2px; }}
QScrollBar::handle {{ background: {p.border}; border-radius: 4px; min-height: 30px; min-width: 30px; }}
QScrollBar::handle:hover {{ background: {p.muted}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}

QSplitter::handle {{ background: transparent; }}
QSplitter::handle:hover {{ background: {p.border}; }}
QMenu {{ background: {p.surface}; border: 1px solid {p.border}; border-radius: 8px; padding: 4px; }}
QMenu::item {{ padding: 6px 22px 6px 10px; border-radius: 6px; }}
QMenu::item:selected {{ background: {p.selection}; }}
QMenu::separator {{ height: 1px; background: {p.border}; margin: 4px 6px; }}
QStatusBar {{ background: {p.bg}; color: {p.muted}; }}
QStatusBar::item {{ border: none; }}
QGraphicsView {{ border: 1px solid {p.border}; border-radius: 8px; background: {p.surface2}; }}
QMessageBox QLabel {{ background: transparent; }}
"""


def qt_palette(p: Palette) -> QPalette:
    pal = QPalette()
    c = QColor
    pal.setColor(QPalette.ColorRole.Window, c(p.bg))
    pal.setColor(QPalette.ColorRole.WindowText, c(p.text))
    pal.setColor(QPalette.ColorRole.Base, c(p.surface2))
    pal.setColor(QPalette.ColorRole.AlternateBase, c(p.surface))
    pal.setColor(QPalette.ColorRole.Text, c(p.text))
    pal.setColor(QPalette.ColorRole.Button, c(p.surface2))
    pal.setColor(QPalette.ColorRole.ButtonText, c(p.text))
    pal.setColor(QPalette.ColorRole.Highlight, c(p.accent))
    pal.setColor(QPalette.ColorRole.HighlightedText, c("#ffffff"))
    pal.setColor(QPalette.ColorRole.ToolTipBase, c(p.surface2))
    pal.setColor(QPalette.ColorRole.ToolTipText, c(p.text))
    pal.setColor(QPalette.ColorRole.PlaceholderText, c(p.muted))
    pal.setColor(QPalette.ColorRole.Link, c(p.accent))
    for role in (QPalette.ColorRole.WindowText, QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText):
        pal.setColor(QPalette.ColorGroup.Disabled, role, c(p.muted))
    return pal


def apply_theme(app: QApplication, name: str) -> Palette:
    global _current
    _current = LIGHT if name == "light" else DARK
    app.setPalette(qt_palette(_current))
    app.setStyleSheet(stylesheet(_current))
    return _current


def checker_pixmap(size: int = 16) -> QPixmap:
    """Sakktábla-minta az átlátszó képrészek megjelenítéséhez."""
    p = _current
    a, b = (QColor("#2a2e38"), QColor("#343945")) if p.name == "dark" else (QColor("#ffffff"), QColor("#e6e9ef"))
    pm = QPixmap(size * 2, size * 2)
    pm.fill(a)
    painter = QPainter(pm)
    painter.fillRect(0, 0, size, size, b)
    painter.fillRect(size, size, size, size, b)
    painter.end()
    return pm


def status_color(status: str) -> QColor:
    p = _current
    return QColor(
        {
            "done": p.success,
            "skipped": p.warning,
            "failed": p.danger,
            "cancelled": p.muted,
            "running": p.accent,
        }.get(status, p.muted)
    )


ICON_SIZE = QSize(18, 18)
