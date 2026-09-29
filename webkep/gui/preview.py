"""Előnézet: eredeti és konvertált kép összehasonlítása szinkron nagyítással."""

from __future__ import annotations

import io
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

from PIL import Image
from PySide6.QtCore import QObject, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QImage, QKeySequence, QPainter, QPixmap, QShortcut, QWheelEvent
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QGraphicsPixmapItem,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..core.converter import PreparedImage, encode, prepare_image
from ..core.formats import output_available
from ..core.settings import ConversionSettings, OutputFormat
from ..i18n import fmt_bytes, fmt_percent, tr
from . import theme
from .widgets import SliderSpin


def pil_to_qimage(img: Image.Image) -> QImage:
    if img.mode != "RGBA":
        img = img.convert("RGBA")
    data = img.tobytes("raw", "RGBA")
    qimg = QImage(data, img.width, img.height, img.width * 4, QImage.Format.Format_RGBA8888)
    return qimg.copy()


class ImageView(QGraphicsView):
    zoomed = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self._item = QGraphicsPixmapItem()
        self._item.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
        self._scene.addItem(self._item)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setRenderHints(QPainter.RenderHint.SmoothPixmapTransform | QPainter.RenderHint.Antialiasing)
        self.setMinimumSize(260, 220)
        self.refresh_background()
        self._fit_mode = True

    def refresh_background(self) -> None:
        self.setBackgroundBrush(QBrush(theme.checker_pixmap()))

    def set_image(self, qimg: QImage | None) -> None:
        if qimg is None:
            self._item.setPixmap(QPixmap())
            return
        self._item.setPixmap(QPixmap.fromImage(qimg))
        self._scene.setSceneRect(QRectF(self._item.pixmap().rect()))

    def has_image(self) -> bool:
        return not self._item.pixmap().isNull()

    def scale_factor(self) -> float:
        return self.transform().m11()

    def set_scale(self, s: float) -> None:
        s = max(0.02, min(32.0, s))
        self._fit_mode = False
        self.resetTransform()
        self.scale(s, s)
        self._item.setTransformationMode(
            Qt.TransformationMode.FastTransformation if s >= 2 else Qt.TransformationMode.SmoothTransformation
        )

    def fit(self) -> None:
        if not self.has_image():
            return
        self._fit_mode = True
        self.resetTransform()
        self.fitInView(self._item, Qt.AspectRatioMode.KeepAspectRatio)
        if self.scale_factor() > 1:
            self.resetTransform()

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        steps = event.angleDelta().y() / 120
        if not steps or not self.has_image():
            return
        factor = 1.2**steps
        new = max(0.02, min(32.0, self.scale_factor() * factor))
        self._fit_mode = False
        self.scale(new / self.scale_factor(), new / self.scale_factor())
        self._item.setTransformationMode(
            Qt.TransformationMode.FastTransformation if new >= 2 else Qt.TransformationMode.SmoothTransformation
        )
        self.zoomed.emit()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self._fit_mode:
            self.fit()


class _Signals(QObject):
    prepared = Signal(int, object)  # generáció, SimpleNamespace (dict-et a Qt átalakítaná)
    encoded = Signal(int, object)
    failed = Signal(int, str)


class PreviewDialog(QDialog):
    apply_quality = Signal(object, int)  # OutputFormat, minőség

    def __init__(self, paths: list[Path], index: int, settings: ConversionSettings, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle(tr("pv.title"))
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, True)
        self.resize(1200, 760)
        self.paths = paths
        self.index = max(0, min(index, len(paths) - 1))
        self.settings = settings.copy()
        self._gen = 0
        self._prepared: PreparedImage | None = None
        self._prepared_path: Path | None = None
        self._source_info: SimpleNamespace | None = None
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="preview")
        self._lock = threading.Lock()
        self._sig = _Signals()
        self._sig.prepared.connect(self._on_prepared)
        self._sig.encoded.connect(self._on_encoded)
        self._sig.failed.connect(self._on_failed)
        self._sync_guard = False
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(220)
        self._debounce.timeout.connect(self._request_encode)
        self._build()
        self._load_current()

    # ------------------------------------------------------------------ UI
    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(10)

        top = QHBoxLayout()
        self.prev_btn = QToolButton()
        self.prev_btn.setIcon(theme.icon("chevron_left"))
        self.prev_btn.setToolTip(tr("pv.prev"))
        self.prev_btn.clicked.connect(lambda: self._step(-1))
        self.next_btn = QToolButton()
        self.next_btn.setIcon(theme.icon("chevron_right"))
        self.next_btn.setToolTip(tr("pv.next"))
        self.next_btn.clicked.connect(lambda: self._step(1))
        self.name_label = QLabel()
        self.name_label.setObjectName("CardTitle")
        top.addWidget(self.prev_btn)
        top.addWidget(self.next_btn)
        top.addWidget(self.name_label, 1)

        top.addWidget(QLabel(tr("pv.format")))
        self.fmt_combo = QComboBox()
        for fmt in (OutputFormat.WEBP, OutputFormat.AVIF):
            if output_available(fmt):
                self.fmt_combo.addItem(fmt.value.upper(), fmt.value)
        first = self.settings.formats[0] if self.settings.formats else OutputFormat.WEBP
        idx = self.fmt_combo.findData(first.value)
        self.fmt_combo.setCurrentIndex(max(0, idx))
        self.fmt_combo.currentIndexChanged.connect(self._on_format_changed)
        top.addWidget(self.fmt_combo)
        top.addSpacing(8)
        top.addWidget(QLabel(tr("q.quality")))
        self.quality = SliderSpin(0, 100, self.settings.quality_for(self._fmt()), " %")
        self.quality.setMinimumWidth(260)
        self.quality.valueChanged.connect(lambda _v: self._debounce.start())
        top.addWidget(self.quality)
        top.addSpacing(8)
        for name, tip, slot in (
            ("fit", tr("pv.fit"), self._fit),
            ("one", tr("pv.actual"), lambda: self._set_scale(1.0)),
            ("zoom_out", tr("pv.zoom_out"), lambda: self._zoom(1 / 1.25)),
            ("zoom_in", tr("pv.zoom_in"), lambda: self._zoom(1.25)),
        ):
            b = QToolButton()
            b.setIcon(theme.icon(name))
            b.setToolTip(tip)
            b.clicked.connect(slot)
            top.addWidget(b)
        self.zoom_label = QLabel("")
        self.zoom_label.setObjectName("Muted")
        self.zoom_label.setMinimumWidth(48)
        top.addWidget(self.zoom_label)
        root.addLayout(top)

        views = QHBoxLayout()
        views.setSpacing(10)
        self.left = ImageView()
        self.right = ImageView()
        left_col, self.left_title = self._titled(self.left)
        right_col, self.right_title = self._titled(self.right)
        views.addLayout(left_col, 1)
        views.addLayout(right_col, 1)
        root.addLayout(views, 1)
        for a, b in ((self.left, self.right), (self.right, self.left)):
            a.horizontalScrollBar().valueChanged.connect(lambda v, b=b: self._sync_scroll(b.horizontalScrollBar(), v))
            a.verticalScrollBar().valueChanged.connect(lambda v, b=b: self._sync_scroll(b.verticalScrollBar(), v))
            a.zoomed.connect(lambda a=a, b=b: self._sync_zoom(a, b))

        info = QHBoxLayout()
        self.left_info = QLabel()
        self.left_info.setObjectName("Muted")
        self.right_info = QLabel()
        self.right_info.setTextFormat(Qt.TextFormat.RichText)
        info.addWidget(self.left_info, 1)
        info.addWidget(self.right_info, 1)
        root.addLayout(info)

        bottom = QHBoxLayout()
        bottom.addWidget(QLabel(tr("pv.hint")), 1)
        self.apply_btn = QPushButton(tr("pv.apply"))
        self.apply_btn.setIcon(theme.icon("check"))
        self.apply_btn.clicked.connect(self._apply)
        close = QPushButton(tr("common.close"))
        close.clicked.connect(self.close)
        bottom.addWidget(self.apply_btn)
        bottom.addWidget(close)
        root.addLayout(bottom)

        QShortcut(QKeySequence(Qt.Key.Key_Left), self, activated=lambda: self._step(-1))
        QShortcut(QKeySequence(Qt.Key.Key_Right), self, activated=lambda: self._step(1))
        QShortcut(QKeySequence("F"), self, activated=self._fit)
        QShortcut(QKeySequence("1"), self, activated=lambda: self._set_scale(1.0))

    def _titled(self, view: ImageView) -> tuple[QVBoxLayout, QLabel]:
        col = QVBoxLayout()
        col.setSpacing(6)
        title = QLabel()
        title.setObjectName("CardTitle")
        col.addWidget(title)
        col.addWidget(view, 1)
        return col, title

    # ------------------------------------------------------------ zoom/sync
    def _sync_scroll(self, bar, value: int) -> None:
        if not self._sync_guard:
            bar.setValue(value)

    def _sync_zoom(self, source: ImageView, other: ImageView) -> None:
        self._sync_guard = True
        other.setTransform(source.transform())
        other._fit_mode = False
        other.horizontalScrollBar().setValue(source.horizontalScrollBar().value())
        other.verticalScrollBar().setValue(source.verticalScrollBar().value())
        self._sync_guard = False
        self._update_zoom_label()

    def _fit(self) -> None:
        self.left.fit()
        self.right.fit()
        self._update_zoom_label()

    def _set_scale(self, s: float) -> None:
        self.left.set_scale(s)
        self._sync_zoom(self.left, self.right)

    def _zoom(self, factor: float) -> None:
        self._set_scale(self.left.scale_factor() * factor)

    def _update_zoom_label(self) -> None:
        self.zoom_label.setText(f"{round(self.left.scale_factor() * 100)}%")

    # --------------------------------------------------------------- logic
    def _fmt(self) -> OutputFormat:
        return OutputFormat(self.fmt_combo.currentData() or OutputFormat.WEBP.value)

    def _on_format_changed(self) -> None:
        fmt = self._fmt()
        self.quality.blockSignals(True)
        self.quality.setValue(self.settings.quality_for(fmt))
        self.quality.blockSignals(False)
        self._request_encode()

    def _step(self, delta: int) -> None:
        if not self.paths:
            return
        self.index = (self.index + delta) % len(self.paths)
        self._load_current()

    def _load_current(self) -> None:
        path = self.paths[self.index]
        self.name_label.setText(f"{path.name}   ({self.index + 1} / {len(self.paths)})")
        self.prev_btn.setEnabled(len(self.paths) > 1)
        self.next_btn.setEnabled(len(self.paths) > 1)
        self.left.set_image(None)
        self.right.set_image(None)
        self.left_title.setText(tr("pv.original"))
        self.right_title.setText(tr("pv.working"))
        self.left_info.setText(tr("pv.loading"))
        self.right_info.setText("")
        self._gen += 1
        gen = self._gen
        self._pool.submit(self._prepare_job, gen, path, self.settings)

    def _prepare_job(self, gen: int, path: Path, settings: ConversionSettings) -> None:
        if gen != self._gen:
            return
        try:
            with Image.open(path) as im:
                src_format = im.format or path.suffix.lstrip(".").upper()
            prepared = prepare_image(path, settings, max_frames=1)
            with self._lock:
                old = self._prepared
                self._prepared = prepared
                self._prepared_path = path
            if old is not None and old is not prepared:
                old.close()
            qimg = pil_to_qimage(prepared.frames[0])
            self._sig.prepared.emit(
                gen,
                SimpleNamespace(
                    qimage=qimg,
                    format=src_format,
                    size=path.stat().st_size,
                    original_dims=prepared.original_dims,
                    dims=prepared.dims,
                ),
            )
        except Exception as exc:
            self._sig.failed.emit(gen, str(exc))

    def _on_prepared(self, gen: int, info: SimpleNamespace) -> None:
        if gen != self._gen:
            return
        self._source_info = info
        self.left.set_image(info.qimage)
        self.left.fit()
        resized = tuple(info.dims) != tuple(info.original_dims)
        self.left_title.setText(tr("pv.original_resized") if resized else tr("pv.original"))
        od, d = info.original_dims, info.dims
        dims = f"{od[0]}×{od[1]}" + (f" → {d[0]}×{d[1]}" if resized else "")
        self.left_info.setText(f"{info.format} · {dims} · {fmt_bytes(info.size)}")
        self._update_zoom_label()
        self._request_encode()

    def _request_encode(self) -> None:
        if self._prepared is None:
            return
        self._gen += 1
        gen = self._gen
        fmt = self._fmt()
        q = self.quality.value()
        self.right_title.setText(tr("pv.working"))
        self._pool.submit(self._encode_job, gen, fmt, q, self.settings)

    def _encode_job(self, gen: int, fmt: OutputFormat, q: int, settings: ConversionSettings) -> None:
        if gen != self._gen:
            return
        try:
            with self._lock:
                prepared = self._prepared
            if prepared is None:
                return
            t0 = time.perf_counter()
            data = encode(prepared, fmt, settings, q)
            elapsed = time.perf_counter() - t0
            with Image.open(io.BytesIO(data)) as im:
                im.load()
                qimg = pil_to_qimage(im)
            self._sig.encoded.emit(gen, SimpleNamespace(qimage=qimg, bytes=len(data), fmt=fmt, q=q, elapsed=elapsed))
        except Exception as exc:
            self._sig.failed.emit(gen, str(exc))

    def _on_encoded(self, gen: int, info: SimpleNamespace) -> None:
        if gen != self._gen:
            return
        had_image = self.right.has_image()
        self.right.set_image(info.qimage)
        if had_image:
            self._sync_zoom(self.left, self.right)
        else:
            self.right.fit()
            self._sync_zoom(self.left, self.right)
        fmt = OutputFormat(info.fmt)
        lossless = self.settings.is_lossless(fmt)
        label = f"{fmt.value.upper()} " + (tr("pv.lossless") if lossless else f"{info.q}%")
        self.right_title.setText(label)
        src = self._source_info.size if self._source_info else 0
        saving = 1 - info.bytes / src if src else 0
        p = theme.current()
        color = p.success if saving > 0 else p.danger
        secs = f"{info.elapsed:.2f}".replace(".", tr("decimal_sep"))
        d = self._source_info.dims if self._source_info else (0, 0)
        self.right_info.setText(
            f"{d[0]}×{d[1]} · <b>{fmt_bytes(info.bytes)}</b> "
            f"<span style='color:{color}; font-weight:600'>({fmt_percent(saving, 1, signed=True)})</span>"
            f" · {tr('pv.encode_time', t=secs)}"
        )

    def _on_failed(self, gen: int, message: str) -> None:
        if gen != self._gen:
            return
        self.right_title.setText(tr("status.failed"))
        self.right_info.setText(f"<span style='color:{theme.current().danger}'>{message}</span>")
        if not self._source_info:
            self.left_info.setText("")

    def _apply(self) -> None:
        self.apply_quality.emit(self._fmt().value, self.quality.value())
        self.settings = self.settings.copy()
        if self._fmt() is OutputFormat.WEBP:
            self.settings.webp.quality = self.quality.value()
        else:
            self.settings.avif.quality = self.quality.value()

    def closeEvent(self, event) -> None:  # noqa: N802
        self._gen += 1
        self._pool.shutdown(wait=False, cancel_futures=True)
        with self._lock:
            # Nem zárjuk le explicit: egy épp futó kódolás még használhatja.
            self._prepared = None
        super().closeEvent(event)
