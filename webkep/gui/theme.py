"""macOS-ihletésű sötét / világos téma: üvegpanelek, paletta, stíluslap, ikonok."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QByteArray, QDir, QEvent, QObject, QPointF, QRectF, QSize, Qt, QTemporaryDir
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontDatabase,
    QIcon,
    QLinearGradient,
    QPainter,
    QPalette,
    QPen,
    QPixmap,
    QRadialGradient,
)
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication, QMenu, QWidget


@dataclass(frozen=True)
class Palette:
    name: str
    bg: str  # ablak alapszín (a színes háttér "alja")
    surface: str  # tömör felület (párbeszédablakok)
    surface2: str  # beviteli mezők alapja (tömör)
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
    # macOS-szerű "üveg" rétegek (r, g, b, alfa 0-255)
    glass: tuple[int, int, int, int] = (40, 40, 46, 178)
    glass_inset: tuple[int, int, int, int] = (255, 255, 255, 12)
    glass_border: tuple[int, int, int, int] = (255, 255, 255, 26)
    glass_highlight: tuple[int, int, int, int] = (255, 255, 255, 22)
    control: tuple[int, int, int, int] = (255, 255, 255, 20)
    control_hover: tuple[int, int, int, int] = (255, 255, 255, 34)
    popup: tuple[int, int, int, int] = (40, 40, 46, 250)
    shadow_alpha: int = 70
    blobs: tuple[str, ...] = ("#3a5bd9", "#8a3ffc", "#0fa3b1", "#d9467a")


DARK = Palette(
    name="dark",
    bg="#16161a",
    surface="#232328",
    surface2="#2c2c32",
    border="#3a3a42",
    text="#f5f5f7",
    muted="#98989f",
    accent="#0a84ff",
    accent_hover="#409cff",
    accent_pressed="#0071e3",
    success="#30d158",
    warning="#ff9f0a",
    danger="#ff453a",
    selection="#1f4f8f",
)

LIGHT = Palette(
    name="light",
    bg="#eceef3",
    surface="#ffffff",
    surface2="#ffffff",
    border="#d2d2d7",
    text="#1d1d1f",
    muted="#6e6e73",
    accent="#007aff",
    accent_hover="#2b8fff",
    accent_pressed="#0062cc",
    success="#28a745",
    warning="#c77700",
    danger="#e0352b",
    selection="#cfe2ff",
    glass=(255, 255, 255, 168),
    glass_inset=(255, 255, 255, 150),
    glass_border=(0, 0, 0, 22),
    glass_highlight=(255, 255, 255, 200),
    control=(255, 255, 255, 215),
    control_hover=(255, 255, 255, 255),
    popup=(250, 250, 252, 250),
    shadow_alpha=34,
    blobs=("#7fa7ff", "#c59bff", "#7fe3d6", "#ffb3c7"),
)

_current: Palette = DARK
_asset_dir: QTemporaryDir | None = None


def rgba(c: tuple[int, int, int, int]) -> str:
    return f"rgba({c[0]}, {c[1]}, {c[2]}, {c[3]})"


def qcolor(c: tuple[int, int, int, int]) -> QColor:
    return QColor(c[0], c[1], c[2], c[3])


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
# Generált képek a stíluslaphoz (nyilak, pipa, macOS-szerű kapcsolók)
# --------------------------------------------------------------------------


def _switch_pixmap(p: Palette, on: bool, enabled: bool, scale: int) -> QPixmap:
    w, h = 34 * scale, 20 * scale
    pm = QPixmap(w, h)
    pm.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    if on:
        track = QColor(p.accent)
    else:
        track = QColor(255, 255, 255, 46) if p.name == "dark" else QColor(0, 0, 0, 34)
    if not enabled:
        track.setAlpha(int(track.alpha() * 0.45))
    painter.setBrush(track)
    painter.drawRoundedRect(QRectF(0, 0, w, h), h / 2, h / 2)
    m = 2 * scale
    d = h - 2 * m
    x = w - m - d if on else m
    painter.setBrush(QColor(0, 0, 0, 40))  # a gomb enyhe árnyéka
    painter.drawEllipse(QRectF(x, m + 0.6 * scale, d, d))
    knob = QColor("#ffffff")
    if not enabled:
        knob.setAlpha(150)
    painter.setBrush(knob)
    painter.drawEllipse(QRectF(x, m, d, d))
    painter.end()
    return pm


def _write_assets(p: Palette) -> Path:
    """A stíluslapban hivatkozott képek generálása ideiglenes mappába."""
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
    for on in (False, True):
        for enabled in (True, False):
            tag = f"switch_{'on' if on else 'off'}{'' if enabled else '_dis'}_{p.name}"
            _switch_pixmap(p, on, enabled, 1).save(str(base / f"{tag}.png"))
            _switch_pixmap(p, on, enabled, 2).save(str(base / f"{tag}@2x.png"))
    return base


# --------------------------------------------------------------------------
# Stíluslap
# --------------------------------------------------------------------------


def stylesheet(p: Palette) -> str:
    assets = _write_assets(p).as_posix()

    def url(name: str) -> str:
        # idézőjelek: a felhasználói mappa neve tartalmazhat szóközt / ékezetet
        return 'url("' + f"{assets}/{name}_{p.name}.png".replace('"', '\\"') + '")'

    down, up, check = url("down"), url("up"), url("check")
    sw_off, sw_on = url("switch_off"), url("switch_on")
    sw_off_dis, sw_on_dis = url("switch_off_dis"), url("switch_on_dis")
    dark = p.name == "dark"
    ctrl, ctrl_hover = rgba(p.control), rgba(p.control_hover)
    hairline = rgba(p.glass_border)
    inset = rgba(p.glass_inset)
    popup = rgba(p.popup)
    focus_ring = "rgba(10, 132, 255, 150)" if dark else "rgba(0, 122, 255, 140)"
    sel = "rgba(10, 132, 255, 70)" if dark else "rgba(0, 122, 255, 46)"
    alt_row = "rgba(255, 255, 255, 7)" if dark else "rgba(0, 0, 0, 9)"
    segment = "rgba(255, 255, 255, 18)" if dark else "rgba(0, 0, 0, 16)"
    segment_on = "rgba(255, 255, 255, 46)" if dark else "rgba(255, 255, 255, 255)"
    scroll = "rgba(255, 255, 255, 50)" if dark else "rgba(0, 0, 0, 60)"
    scroll_hover = "rgba(255, 255, 255, 90)" if dark else "rgba(0, 0, 0, 100)"
    groove = "rgba(255, 255, 255, 40)" if dark else "rgba(0, 0, 0, 30)"
    return f"""
* {{ outline: none; }}
QWidget {{ color: {p.text}; font-size: 10pt; }}
QMainWindow, QDialog {{ background: {p.bg}; }}
QWidget#Root {{ background: transparent; }}
QToolTip {{ background: {popup}; color: {p.text}; border: 1px solid {hairline};
    border-radius: 8px; padding: 6px 9px; }}

QFrame#Card {{ background: transparent; border: none; }}
QFrame#Card QLabel, QFrame#Card QCheckBox, QFrame#Card QRadioButton {{ background: transparent; }}
QLabel#CardTitle {{ font-size: 10.5pt; font-weight: 600; }}
QLabel#Muted, QLabel#Hint {{ color: {p.muted}; }}
QLabel#Hint {{ font-size: 9pt; }}
QLabel#AppTitle {{ font-size: 14pt; font-weight: 700; }}
QLabel#Version {{ color: {p.muted}; font-size: 9pt; }}
QLabel#BigStat {{ font-size: 18pt; font-weight: 700; }}
QLabel#Badge {{ background: {segment}; border: none; border-radius: 9px;
    padding: 2px 9px; color: {p.muted}; font-size: 9pt; }}
QLabel#Success {{ color: {p.success}; font-weight: 600; }}
QLabel#Warning {{ color: {p.warning}; font-weight: 600; }}
QLabel#Danger {{ color: {p.danger}; font-weight: 600; }}
QLabel#DropHint {{ color: {p.muted}; font-size: 12pt; font-weight: 600; }}

QPushButton {{ background: {ctrl}; border: 1px solid {hairline}; border-radius: 8px;
    padding: 6px 14px; }}
QPushButton:hover {{ background: {ctrl_hover}; }}
QPushButton:pressed {{ background: {segment}; }}
QPushButton:disabled {{ color: {p.muted}; background: {segment}; }}
QPushButton:checked {{ background: {sel}; border-color: {p.accent}; }}
QToolButton {{ background: transparent; border: 1px solid transparent; border-radius: 8px; padding: 5px; }}
QToolButton:hover {{ background: {ctrl}; border-color: {hairline}; }}
QToolButton:pressed {{ background: {segment}; }}
QToolButton:disabled {{ color: {p.muted}; }}
QToolButton:checked {{ background: {sel}; }}
QPushButton#Primary {{ background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {p.accent_hover}, stop:1 {p.accent});
    color: #ffffff; border: 1px solid {p.accent_pressed}; font-weight: 600; padding: 8px 22px; }}
QPushButton#Primary:hover {{ background: {p.accent_hover}; }}
QPushButton#Primary:pressed {{ background: {p.accent_pressed}; }}
QPushButton#Primary:disabled {{ background: {segment}; border-color: transparent; color: {p.muted}; }}
QPushButton#Danger:hover {{ color: {p.danger}; border-color: {p.danger}; }}
QToolButton::menu-indicator {{ image: none; width: 0; }}
QPushButton::menu-indicator {{ image: {down}; subcontrol-position: right center; right: 6px; }}

QLineEdit, QSpinBox, QComboBox, QPlainTextEdit, QTextBrowser {{ background: {ctrl};
    border: 1px solid {hairline}; border-radius: 8px; padding: 5px 9px;
    selection-background-color: {p.accent}; selection-color: #ffffff; }}
QLineEdit:hover, QSpinBox:hover, QComboBox:hover {{ background: {ctrl_hover}; }}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus, QPlainTextEdit:focus {{ border: 1px solid {focus_ring}; }}
QLineEdit:disabled, QSpinBox:disabled, QComboBox:disabled {{ color: {p.muted}; background: {segment}; }}
QPlainTextEdit#Log {{ background: {inset}; font-family: "SF Mono", "Cascadia Mono", "Consolas",
    "DejaVu Sans Mono", monospace; font-size: 9pt; }}
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
QComboBox QAbstractItemView {{ background: {p.surface}; border: 1px solid {hairline};
    border-radius: 8px; selection-background-color: {p.accent}; selection-color: #ffffff;
    padding: 4px; outline: none; }}

QCheckBox, QRadioButton {{ spacing: 9px; background: transparent; }}
QCheckBox::indicator {{ width: 34px; height: 20px; border: none; image: {sw_off}; }}
QCheckBox::indicator:checked {{ image: {sw_on}; }}
QCheckBox::indicator:disabled {{ image: {sw_off_dis}; }}
QCheckBox::indicator:checked:disabled {{ image: {sw_on_dis}; }}
QCheckBox:disabled, QRadioButton:disabled {{ color: {p.muted}; }}

QSlider {{ background: transparent; }}
QSlider::groove:horizontal {{ height: 4px; background: {groove}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {p.accent}; border-radius: 2px; }}
QSlider::sub-page:horizontal:disabled {{ background: {p.muted}; }}
QSlider::handle:horizontal {{ background: #ffffff; border: 1px solid rgba(0, 0, 0, 40);
    width: 18px; height: 18px; margin: -8px 0; border-radius: 10px; }}
QSlider::handle:horizontal:hover {{ background: #f2f2f7; }}
QSlider::handle:horizontal:disabled {{ background: {p.muted}; }}

QTabWidget::pane {{ border: none; background: transparent; top: 6px; }}
QTabWidget::tab-bar {{ alignment: center; }}
QTabBar {{ background: transparent; }}
QTabBar::tab {{ background: {segment}; color: {p.text}; padding: 6px 14px; margin: 0;
    border: none; min-width: 52px; }}
QTabBar::tab:first {{ border-top-left-radius: 9px; border-bottom-left-radius: 9px; }}
QTabBar::tab:last {{ border-top-right-radius: 9px; border-bottom-right-radius: 9px; }}
QTabBar::tab:selected {{ background: {segment_on}; font-weight: 600; border-radius: 8px; }}
QTabBar::tab:hover:!selected {{ background: {ctrl_hover}; }}

QTableView {{ background: transparent; alternate-background-color: {alt_row}; border: none;
    gridline-color: transparent; selection-background-color: {sel}; selection-color: {p.text}; }}
QTableView::item {{ padding: 0 6px; border: none; }}
QTableView::indicator {{ width: 16px; height: 16px; border-radius: 5px; border: 1px solid {hairline};
    background: {ctrl}; }}
QTableView::indicator:checked {{ background: {p.accent}; border-color: {p.accent}; image: {check}; }}
QHeaderView {{ background: transparent; border: none; }}
QHeaderView::section {{ background: transparent; color: {p.muted}; border: none;
    border-bottom: 1px solid {hairline}; padding: 6px 8px; font-weight: 600; font-size: 9pt; }}
QHeaderView::section:hover {{ color: {p.text}; }}
QTableCornerButton::section {{ background: transparent; border: none; }}

QProgressBar {{ background: {segment}; border: none; border-radius: 10px;
    text-align: center; min-height: 20px; color: {p.text}; font-weight: 600; }}
QProgressBar::chunk {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {p.accent}, stop:1 #af52de);
    border-radius: 10px; }}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 3px 2px; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px 3px; }}
QScrollBar::handle {{ background: {scroll}; border-radius: 3px; min-height: 30px; min-width: 30px; }}
QScrollBar::handle:hover {{ background: {scroll_hover}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QStackedWidget, QStackedWidget > QWidget {{ background: transparent; }}

QSplitter, QSplitter::handle {{ background: transparent; }}
QMenu {{ background: {popup}; border: 1px solid {hairline}; border-radius: 11px; padding: 5px; }}
QMenu::item {{ padding: 6px 22px 6px 12px; border-radius: 6px; background: transparent; }}
QMenu::item:selected {{ background: {p.accent}; color: #ffffff; }}
QMenu::item:disabled {{ color: {p.muted}; }}
QMenu::separator {{ height: 1px; background: {hairline}; margin: 5px 8px; }}
QMenu::icon {{ padding-left: 6px; }}
QStatusBar {{ background: transparent; color: {p.muted}; }}
QStatusBar::item {{ border: none; }}
QGraphicsView {{ border: 1px solid {hairline}; border-radius: 12px; background: {p.surface2}; }}
QMessageBox, QInputDialog {{ background: {p.surface}; }}
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


# --------------------------------------------------------------------------
# macOS-szerű elemek: betűtípus, színes elmosott háttér, lebegő üveg menük
# --------------------------------------------------------------------------

_FONT_CANDIDATES = (
    "SF Pro Text",
    ".AppleSystemUIFont",
    "Segoe UI Variable Text",
    "Segoe UI Variable",
    "Inter",
    "Helvetica Neue",
    "Segoe UI",
)


def apply_font(app: QApplication) -> None:
    families = set(QFontDatabase.families())
    for name in _FONT_CANDIDATES:
        if name in families:
            font = QFont(name, 10)
            font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
            app.setFont(font)
            return


_backdrop_cache: dict[tuple, QPixmap] = {}


def backdrop_pixmap(width: int, height: int) -> QPixmap:
    """A macOS „vibrancy” hatását idéző háttér: lágy, elmosott színfoltok.

    Erre kerülnek az áttetsző üvegpanelek, így azok enyhén átszínezve
    „úsznak” a háttér felett. Méretenként gyorsítótárazva."""
    p = _current
    key = (p.name, width, height)
    cached = _backdrop_cache.get(key)
    if cached is not None:
        return cached
    if len(_backdrop_cache) > 6:
        _backdrop_cache.clear()
    pm = QPixmap(max(1, width), max(1, height))
    pm.fill(QColor(p.bg))
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    span = max(width, height)
    spots = ((0.12, 0.08, 0.62), (0.88, 0.18, 0.55), (0.25, 0.95, 0.6), (0.85, 0.92, 0.5))
    strength = 120 if p.name == "dark" else 150
    for (fx, fy, fr), color in zip(spots, p.blobs):
        cx, cy, r = fx * width, fy * height, fr * span
        grad = QRadialGradient(QPointF(cx, cy), r)
        c0 = QColor(color)
        c0.setAlpha(strength)
        c1 = QColor(color)
        c1.setAlpha(0)
        grad.setColorAt(0.0, c0)
        grad.setColorAt(1.0, c1)
        painter.setBrush(QBrush(grad))
        painter.drawEllipse(QPointF(cx, cy), r, r)
    painter.end()
    _backdrop_cache[key] = pm
    return pm


def paint_glass(
    painter: QPainter,
    rect: QRectF,
    radius: float = 14.0,
    shadow: bool = True,
    inset: bool = False,
) -> None:
    """Lebegő üvegpanel: puha árnyék, áttetsző kitöltés, finom keret és felső fény."""
    p = _current
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    if shadow:
        layers = 7
        for i in range(layers, 0, -1):
            a = int(p.shadow_alpha * (1 - i / (layers + 1)) ** 2 / 2.2)
            painter.setBrush(QColor(0, 0, 0, a))
            grow = i * 0.9
            painter.drawRoundedRect(rect.adjusted(-grow, -grow + 2, grow, grow + 2), radius + grow, radius + grow)
    painter.setBrush(qcolor(p.glass_inset if inset else p.glass))
    painter.drawRoundedRect(rect, radius, radius)
    # felső fényvisszaverődés
    top = QLinearGradient(rect.topLeft(), QPointF(rect.left(), rect.top() + min(60.0, rect.height())))
    hl = qcolor(p.glass_highlight)
    top.setColorAt(0.0, QColor(hl.red(), hl.green(), hl.blue(), hl.alpha() // (3 if inset else 2)))
    top.setColorAt(1.0, QColor(hl.red(), hl.green(), hl.blue(), 0))
    painter.setBrush(QBrush(top))
    painter.drawRoundedRect(rect, radius, radius)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(QPen(qcolor(p.glass_border), 1))
    painter.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)


class _GlassPopupFilter(QObject):
    """A menüket lekerekített, áttetsző („lebegő üveg”) ablakká teszi, és az új
    ablakok rendszer-címsorát a témához igazítja."""

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if (
            event.type() == QEvent.Type.Show
            and isinstance(obj, QWidget)
            and obj.isWindow()
            and not isinstance(obj, QMenu)
            and obj.property("_webkep_titlebar") != _current.name
        ):
            obj.setProperty("_webkep_titlebar", _current.name)
            set_native_titlebar(obj, _current.name == "dark")
        if event.type() == QEvent.Type.Polish and isinstance(obj, QMenu) and not obj.property("_webkep_glass"):
            obj.setProperty("_webkep_glass", True)
            obj.setWindowFlags(
                obj.windowFlags() | Qt.WindowType.FramelessWindowHint | Qt.WindowType.NoDropShadowWindowHint
            )
            obj.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        return False


_popup_filter: _GlassPopupFilter | None = None


def set_native_titlebar(widget, dark: bool) -> None:
    """Windows 10/11: sötét témánál a rendszer címsora is sötét legyen."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        hwnd = int(widget.winId())
        value = ctypes.c_int(1 if dark else 0)
        for attr in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE (új és régi azonosító)
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(value), ctypes.sizeof(value)) == 0:
                break
    except Exception:
        pass


def apply_theme(app: QApplication, name: str) -> Palette:
    global _current, _popup_filter
    _current = LIGHT if name == "light" else DARK
    _backdrop_cache.clear()
    if _popup_filter is None:
        _popup_filter = _GlassPopupFilter(app)
        app.installEventFilter(_popup_filter)
    app.setPalette(qt_palette(_current))
    app.setStyleSheet(stylesheet(_current))
    for w in app.topLevelWidgets():
        if w.isWindow() and w.isVisible() and not isinstance(w, QMenu):
            w.setProperty("_webkep_titlebar", _current.name)
            set_native_titlebar(w, _current.name == "dark")
            w.update()
    return _current


def checker_pixmap(size: int = 16) -> QPixmap:
    """Sakktábla-minta az átlátszó képrészek megjelenítéséhez."""
    p = _current
    a, b = (QColor("#2a2a30"), QColor("#34343b")) if p.name == "dark" else (QColor("#ffffff"), QColor("#e8e8ed"))
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
