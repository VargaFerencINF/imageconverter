"""Újrahasznosítható vezérlők."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QDir, Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QCompleter,
    QFileDialog,
    QFileSystemModel,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..i18n import tr
from . import theme


class Card(QFrame):
    """Lekerekített, keretes panel opcionális címmel."""

    def __init__(self, title: str = "", parent: QWidget | None = None, icon_name: str | None = None):
        super().__init__(parent)
        self.setObjectName("Card")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(14, 12, 14, 14)
        self._layout.setSpacing(10)
        self.header = QHBoxLayout()
        self.header.setSpacing(8)
        self.title_label: QLabel | None = None
        self.icon_label: QLabel | None = None
        self.icon_name = icon_name
        if title:
            if icon_name:
                self.icon_label = QLabel()
                self.icon_label.setPixmap(theme.icon(icon_name, "accent").pixmap(18, 18))
                self.header.addWidget(self.icon_label)
            self.title_label = QLabel(title)
            self.title_label.setObjectName("CardTitle")
            self.header.addWidget(self.title_label)
            self.header.addStretch(1)
            self._layout.addLayout(self.header)

    def body(self) -> QVBoxLayout:
        return self._layout

    def refresh_icon(self) -> None:
        if self.icon_label and self.icon_name:
            self.icon_label.setPixmap(theme.icon(self.icon_name, "accent").pixmap(18, 18))


def hint(text: str, wrap: bool = True) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("Hint")
    lbl.setWordWrap(wrap)
    return lbl


class SliderSpin(QWidget):
    """Csúszka + számmező, szinkronban; alatta opcionális bal/jobb felirat."""

    valueChanged = Signal(int)

    def __init__(
        self,
        minimum: int,
        maximum: int,
        value: int,
        suffix: str = "",
        left_caption: str = "",
        right_caption: str = "",
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(0)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(minimum, maximum)
        self.slider.setValue(value)
        self.slider.setPageStep(max(1, (maximum - minimum) // 10))
        self.spin = QSpinBox()
        self.spin.setRange(minimum, maximum)
        self.spin.setValue(value)
        self.spin.setSuffix(suffix)
        self.spin.setFixedWidth(92)
        self.spin.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        grid.addWidget(self.slider, 0, 0, 1, 2)
        grid.addWidget(self.spin, 0, 2)
        if left_caption or right_caption:
            left = hint(left_caption, wrap=False)
            right = hint(right_caption, wrap=False)
            right.setAlignment(Qt.AlignmentFlag.AlignRight)
            for cap in (left, right):  # a feliratok ne szabják meg a minimális szélességet
                cap.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            self.slider.setMinimumWidth(176)
            grid.addWidget(left, 1, 0)
            grid.addWidget(right, 1, 1)
        self.slider.valueChanged.connect(self._from_slider)
        self.spin.valueChanged.connect(self._from_spin)

    def _from_slider(self, v: int) -> None:
        if self.spin.value() != v:
            self.spin.setValue(v)
        self.valueChanged.emit(v)

    def _from_spin(self, v: int) -> None:
        if self.slider.value() != v:
            self.slider.setValue(v)

    def value(self) -> int:
        return self.spin.value()

    def setValue(self, v: int) -> None:  # noqa: N802 - Qt stílus
        self.slider.setValue(int(v))


class PathPicker(QWidget):
    """Mappaválasztó: szövegmező automatikus kiegészítéssel, tallózás,
    legutóbbi mappák menü és fogd-és-vidd támogatás."""

    pathChanged = Signal(str)

    def __init__(self, dialog_title: str, icon_name: str = "folder", parent: QWidget | None = None):
        super().__init__(parent)
        self.dialog_title = dialog_title
        self.icon_name = icon_name
        self._recent: list[str] = []
        self._last = ""
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self.edit = QLineEdit()
        self.edit.setClearButtonEnabled(True)
        self.edit.setAcceptDrops(False)
        fs_model = QFileSystemModel(self)
        fs_model.setFilter(QDir.Filter.AllDirs | QDir.Filter.NoDotAndDotDot | QDir.Filter.Drives)
        fs_model.setRootPath("")
        completer = QCompleter(fs_model, self)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.edit.setCompleter(completer)
        self.edit.editingFinished.connect(self._commit)
        self.recent_btn = QToolButton()
        self.recent_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.recent_btn.setToolTip(tr("picker.recent"))
        self.recent_menu = QMenu(self)
        self.recent_btn.setMenu(self.recent_menu)
        self.browse_btn = QPushButton(tr("picker.browse"))
        self.browse_btn.clicked.connect(self.browse)
        lay.addWidget(self.edit, 1)
        lay.addWidget(self.recent_btn)
        lay.addWidget(self.browse_btn)
        self.setAcceptDrops(True)
        self.refresh_icons()
        self._rebuild_recent()

    def refresh_icons(self) -> None:
        self.browse_btn.setIcon(theme.icon(self.icon_name))
        self.recent_btn.setIcon(theme.icon("chevron_down", "muted"))

    def path(self) -> str:
        return self.edit.text().strip()

    def setPath(self, path: str, emit: bool = True) -> None:  # noqa: N802
        self.edit.setText(str(path))
        if emit:
            self._commit()
        else:
            self._last = self.path()

    def setRecent(self, items: list[str]) -> None:  # noqa: N802
        self._recent = list(items)
        self._rebuild_recent()

    def _rebuild_recent(self) -> None:
        self.recent_menu.clear()
        if not self._recent:
            act = self.recent_menu.addAction(tr("picker.no_recent"))
            act.setEnabled(False)
            return
        for item in self._recent:
            act = self.recent_menu.addAction(item)
            act.triggered.connect(lambda _=False, p=item: self.setPath(p))

    def _commit(self) -> None:
        current = self.path()
        if current != self._last:
            self._last = current
            self.pathChanged.emit(current)

    def browse(self) -> None:
        start = self.path() if self.path() and Path(self.path()).exists() else str(Path.home())
        chosen = QFileDialog.getExistingDirectory(self, self.dialog_title, start)
        if chosen:
            self.setPath(QDir.toNativeSeparators(chosen))

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        urls = event.mimeData().urls()
        if urls and urls[0].isLocalFile():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        p = Path(event.mimeData().urls()[0].toLocalFile())
        if p.is_file():
            p = p.parent
        self.setPath(QDir.toNativeSeparators(str(p)))
        event.acceptProposedAction()


def labeled_row(grid: QGridLayout, row: int, label: str, widget: QWidget, tooltip: str = "") -> QLabel:
    lbl = QLabel(label)
    lbl.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
    if tooltip:
        lbl.setToolTip(tooltip)
        widget.setToolTip(tooltip)
    grid.addWidget(lbl, row, 0, Qt.AlignmentFlag.AlignVCenter)
    grid.addWidget(widget, row, 1)
    return lbl


def form_grid() -> QGridLayout:
    grid = QGridLayout()
    grid.setContentsMargins(0, 0, 0, 0)
    grid.setHorizontalSpacing(12)
    grid.setVerticalSpacing(10)
    grid.setColumnStretch(1, 1)
    grid.setColumnMinimumWidth(0, 110)
    return grid
