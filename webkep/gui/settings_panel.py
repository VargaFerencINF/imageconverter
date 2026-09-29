"""A jobb oldali, füles beállítópanel."""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import TypeVar

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..core.batch import cpu_count
from ..core.formats import heif_available, output_available
from ..core.naming import output_name
from ..core.resize import plan_resize
from ..core.settings import (
    AVIF_SUBSAMPLINGS,
    INPUT_GROUP_KEYS,
    ColorProfile,
    ConflictPolicy,
    ConversionSettings,
    OutputFormat,
    Resample,
    ResizeMode,
)
from ..i18n import tr
from . import theme
from .widgets import Card, SliderSpin, form_grid, hint, labeled_row


def quality_caption(q: int, fmt: OutputFormat, lossless: bool = False) -> str:
    if lossless:
        return tr("q.lossless_caption")
    # Az AVIF skála "erősebb": ugyanaz a látható minőség kisebb számnál jön ki.
    bands = (90, 75, 60, 40) if fmt is OutputFormat.WEBP else (80, 60, 45, 30)
    if q >= bands[0]:
        key = "q.excellent"
    elif q >= bands[1]:
        key = "q.very_good"
    elif q >= bands[2]:
        key = "q.good"
    elif q >= bands[3]:
        key = "q.medium"
    else:
        key = "q.low"
    return tr("q.caption", label=tr(key), loss=100 - q)


def _combo(items: list[tuple[str, object]]) -> QComboBox:
    # A Qt a str-alapú Enum értékeket sima str-ként adja vissza, ezért
    # az értéket tároljuk, és olvasáskor alakítjuk vissza (_enum_data).
    cb = QComboBox()
    # hosszú elemeknél se nőjön túl szélesre (a lenyíló lista teljes szélességű marad)
    cb.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
    cb.setMinimumContentsLength(14)
    for text, data in items:
        cb.addItem(text, data.value if isinstance(data, Enum) else data)
    cb.view().setMinimumWidth(cb.view().sizeHintForColumn(0) + 24)
    return cb


def _set_combo(cb: QComboBox, data: object) -> None:
    idx = cb.findData(data.value if isinstance(data, Enum) else data)
    if idx >= 0:
        cb.setCurrentIndex(idx)


E = TypeVar("E", bound=Enum)


def _enum_data(cb: QComboBox, cls: type[E]) -> E:
    return cls(cb.currentData())


def _scroll(widget: QWidget) -> QScrollArea:
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QScrollArea.Shape.NoFrame)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    area.setWidget(widget)
    return area


def _page() -> tuple[QWidget, QVBoxLayout]:
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(10, 12, 10, 12)
    lay.setSpacing(12)
    return w, lay


class SettingsPanel(QWidget):
    changed = Signal()  # a konverziós beállítások (preset-tartalom) változtak
    app_options_changed = Signal()  # bemeneti típusok, szálak, befejezési opciók
    groups_changed = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._loading = False
        self._cards: list[Card] = []
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(False)
        root.addWidget(self.tabs)
        self.tabs.addTab(_scroll(self._build_format_tab()), tr("tab.format"))
        self.tabs.addTab(_scroll(self._build_resize_tab()), tr("tab.resize"))
        self.tabs.addTab(_scroll(self._build_meta_tab()), tr("tab.meta"))
        self.tabs.addTab(_scroll(self._build_output_tab()), tr("tab.output"))
        self.tabs.addTab(_scroll(self._build_advanced_tab()), tr("tab.advanced"))
        self.set_settings(ConversionSettings())
        self._connect_all()
        self.refresh_icons()
        # A panel legalább olyan széles legyen, hogy egyik fül tartalma se vágódjon le.
        widest = max(self.tabs.widget(i).widget().minimumSizeHint().width() for i in range(self.tabs.count()))
        self.setMinimumWidth(widest + 28)

    def _card(self, title: str, icon_name: str | None = None) -> Card:
        card = Card(title, icon_name=icon_name)
        self._cards.append(card)
        return card

    # ------------------------------------------------------------------ tabs
    def _build_format_tab(self) -> QWidget:
        page, lay = _page()

        card = self._card(tr("fmt.output_formats"), "image")
        row = QHBoxLayout()
        row.setSpacing(18)
        self.chk_webp = QCheckBox("WebP")
        self.chk_webp.setToolTip(tr("fmt.webp_tip"))
        self.chk_avif = QCheckBox("AVIF")
        self.chk_avif.setToolTip(tr("fmt.avif_tip"))
        if not output_available(OutputFormat.AVIF):
            self.chk_avif.setEnabled(False)
            self.chk_avif.setToolTip(tr("err.format_unavailable", fmt="AVIF"))
        row.addWidget(self.chk_webp)
        row.addWidget(self.chk_avif)
        row.addStretch(1)
        card.body().addLayout(row)
        card.body().addWidget(hint(tr("fmt.both_hint")))
        self.chk_anim = QCheckBox(tr("fmt.keep_animation"))
        self.chk_anim.setToolTip(tr("fmt.keep_animation_tip"))
        card.body().addWidget(self.chk_anim)
        lay.addWidget(card)

        # WebP
        self.webp_card = self._card("WebP")
        g = form_grid()
        self.webp_q = SliderSpin(0, 100, 80, " %", tr("q.smaller"), tr("q.better"))
        labeled_row(g, 0, tr("q.quality"), self.webp_q, tr("q.quality_tip"))
        self.webp_q_caption = hint("")
        g.addWidget(self.webp_q_caption, 1, 1)
        self.webp_lossless = QCheckBox(tr("webp.lossless"))
        self.webp_lossless.setToolTip(tr("webp.lossless_tip"))
        g.addWidget(self.webp_lossless, 2, 0, 1, 2)
        self.webp_method = SliderSpin(0, 6, 4, "", tr("webp.faster"), tr("webp.smaller"))
        labeled_row(g, 3, tr("webp.method"), self.webp_method, tr("webp.method_tip"))
        self.webp_alpha = SliderSpin(0, 100, 100, " %")
        labeled_row(g, 4, tr("webp.alpha_quality"), self.webp_alpha, tr("webp.alpha_quality_tip"))
        self.webp_exact = QCheckBox(tr("webp.exact"))
        self.webp_exact.setToolTip(tr("webp.exact_tip"))
        g.addWidget(self.webp_exact, 5, 0, 1, 2)
        self.webp_card.body().addLayout(g)
        lay.addWidget(self.webp_card)

        # AVIF
        self.avif_card = self._card("AVIF")
        g = form_grid()
        self.avif_q = SliderSpin(0, 100, 60, " %", tr("q.smaller"), tr("q.better"))
        labeled_row(g, 0, tr("q.quality"), self.avif_q, tr("q.quality_tip"))
        self.avif_q_caption = hint("")
        g.addWidget(self.avif_q_caption, 1, 1)
        self.avif_lossless = QCheckBox(tr("avif.lossless"))
        self.avif_lossless.setToolTip(tr("avif.lossless_tip"))
        g.addWidget(self.avif_lossless, 2, 0, 1, 2)
        self.avif_speed = SliderSpin(0, 10, 6, "", tr("avif.slower"), tr("avif.faster"))
        labeled_row(g, 3, tr("avif.speed"), self.avif_speed, tr("avif.speed_tip"))
        self.avif_sub = _combo([(tr(f"avif.sub.{s.replace(':', '')}"), s) for s in AVIF_SUBSAMPLINGS])
        labeled_row(g, 4, tr("avif.subsampling"), self.avif_sub, tr("avif.subsampling_tip"))
        self.avif_card.body().addLayout(g)
        self.avif_card.body().addWidget(hint(tr("avif.scale_hint")))
        lay.addWidget(self.avif_card)
        lay.addStretch(1)
        return page

    def _build_resize_tab(self) -> QWidget:
        page, lay = _page()
        card = self._card(tr("rs.title"), "fit")
        g = form_grid()
        self.rs_mode = _combo([(tr(f"rs.mode.{m.value}"), m) for m in ResizeMode])
        labeled_row(g, 0, tr("rs.mode"), self.rs_mode)
        card.body().addLayout(g)

        self.rs_stack = QStackedWidget()
        self.rs_percent = QSpinBox()
        self.rs_percent.setRange(1, 1000)
        self.rs_percent.setSuffix(" %")
        self.rs_width = QSpinBox()
        self.rs_width.setRange(1, 65535)
        self.rs_width.setSuffix(" px")
        self.rs_height = QSpinBox()
        self.rs_height.setRange(1, 65535)
        self.rs_height.setSuffix(" px")
        self.rs_long = QSpinBox()
        self.rs_long.setRange(1, 65535)
        self.rs_long.setSuffix(" px")
        self.rs_box_w = QSpinBox()
        self.rs_box_w.setRange(1, 65535)
        self.rs_box_w.setSuffix(" px")
        self.rs_box_h = QSpinBox()
        self.rs_box_h.setRange(1, 65535)
        self.rs_box_h.setSuffix(" px")

        def param_page(rows: list[tuple[str, QWidget]]) -> QWidget:
            w = QWidget()
            gl = form_grid()
            w.setLayout(gl)
            for i, (label, widget) in enumerate(rows):
                labeled_row(gl, i, label, widget)
            return w

        self._rs_pages = {
            ResizeMode.NONE: QWidget(),
            ResizeMode.PERCENT: param_page([(tr("rs.percent"), self.rs_percent)]),
            ResizeMode.WIDTH: param_page([(tr("rs.width"), self.rs_width)]),
            ResizeMode.HEIGHT: param_page([(tr("rs.height"), self.rs_height)]),
            ResizeMode.LONG_EDGE: param_page([(tr("rs.long_edge"), self.rs_long)]),
        }
        box_page = param_page([(tr("rs.box_width"), self.rs_box_w), (tr("rs.box_height"), self.rs_box_h)])
        for page_widget in self._rs_pages.values():
            self.rs_stack.addWidget(page_widget)
        self.rs_stack.addWidget(box_page)
        self._rs_pages[ResizeMode.FIT] = box_page
        self._rs_pages[ResizeMode.FILL] = box_page
        card.body().addWidget(self.rs_stack)

        self.rs_upscale = QCheckBox(tr("rs.upscale"))
        self.rs_upscale.setToolTip(tr("rs.upscale_tip"))
        card.body().addWidget(self.rs_upscale)
        self.rs_example = hint("")
        card.body().addWidget(self.rs_example)
        lay.addWidget(card)

        card = self._card(tr("rs.quality_title"), "sliders")
        g = form_grid()
        self.rs_filter = _combo([(tr(f"rs.filter.{r.value}"), r) for r in Resample])
        labeled_row(g, 0, tr("rs.filter"), self.rs_filter, tr("rs.filter_tip"))
        self.rs_sharpen = QCheckBox(tr("rs.sharpen"))
        self.rs_sharpen.setToolTip(tr("rs.sharpen_tip"))
        g.addWidget(self.rs_sharpen, 1, 0, 1, 2)
        self.rs_sharpen_amount = SliderSpin(1, 200, 60, " %", tr("rs.subtle"), tr("rs.strong"))
        labeled_row(g, 2, tr("rs.sharpen_amount"), self.rs_sharpen_amount)
        card.body().addLayout(g)
        lay.addWidget(card)
        lay.addStretch(1)
        return page

    def _build_meta_tab(self) -> QWidget:
        page, lay = _page()
        card = self._card(tr("md.title"), "info")
        self.md_orient = QCheckBox(tr("md.auto_orient"))
        self.md_orient.setToolTip(tr("md.auto_orient_tip"))
        self.md_exif = QCheckBox(tr("md.keep_exif"))
        self.md_exif.setToolTip(tr("md.keep_exif_tip"))
        self.md_gps = QCheckBox(tr("md.strip_gps"))
        self.md_gps.setToolTip(tr("md.strip_gps_tip"))
        gps_row = QHBoxLayout()
        gps_row.setContentsMargins(26, 0, 0, 0)
        gps_row.addWidget(self.md_gps)
        self.md_xmp = QCheckBox(tr("md.keep_xmp"))
        self.md_xmp.setToolTip(tr("md.keep_xmp_tip"))
        self.md_times = QCheckBox(tr("md.timestamps"))
        self.md_times.setToolTip(tr("md.timestamps_tip"))
        for w in (self.md_orient, self.md_exif):
            card.body().addWidget(w)
        card.body().addLayout(gps_row)
        card.body().addWidget(self.md_xmp)
        card.body().addWidget(self.md_times)
        card.body().addWidget(hint(tr("md.privacy_hint")))
        lay.addWidget(card)

        card = self._card(tr("md.color_title"), "sun")
        g = form_grid()
        self.md_color = _combo([(tr(f"md.color.{c.value}"), c) for c in ColorProfile])
        labeled_row(g, 0, tr("md.color"), self.md_color)
        card.body().addLayout(g)
        card.body().addWidget(hint(tr("md.color_hint")))
        lay.addWidget(card)
        lay.addStretch(1)
        return page

    def _build_output_tab(self) -> QWidget:
        page, lay = _page()
        card = self._card(tr("nm.title"), "files")
        g = form_grid()
        self.nm_prefix = QLineEdit()
        self.nm_prefix.setPlaceholderText(tr("nm.prefix_ph"))
        labeled_row(g, 0, tr("nm.prefix"), self.nm_prefix)
        self.nm_suffix = QLineEdit()
        self.nm_suffix.setPlaceholderText(tr("nm.suffix_ph"))
        labeled_row(g, 1, tr("nm.suffix"), self.nm_suffix)
        self.nm_websafe = QCheckBox(tr("nm.web_safe"))
        self.nm_websafe.setToolTip(tr("nm.web_safe_tip"))
        g.addWidget(self.nm_websafe, 2, 0, 1, 2)
        self.nm_lower = QCheckBox(tr("nm.lowercase"))
        g.addWidget(self.nm_lower, 3, 0, 1, 2)
        self.nm_conflict = _combo([(tr(f"nm.conflict.{c.value}"), c) for c in ConflictPolicy])
        labeled_row(g, 4, tr("nm.conflict"), self.nm_conflict, tr("nm.conflict_tip"))
        card.body().addLayout(g)
        self.nm_example = hint("")
        self.nm_example.setTextFormat(Qt.TextFormat.RichText)
        card.body().addWidget(self.nm_example)
        lay.addWidget(card)

        card = self._card(tr("sz.title"), "gauge")
        g = form_grid()
        self.sz_target = QCheckBox(tr("sz.target"))
        self.sz_target.setToolTip(tr("sz.target_tip"))
        g.addWidget(self.sz_target, 0, 0, 1, 2)
        self.sz_kb = QSpinBox()
        self.sz_kb.setRange(1, 1_000_000)
        self.sz_kb.setSuffix(" KB")
        labeled_row(g, 1, tr("sz.max_size"), self.sz_kb)
        self.sz_minq = SliderSpin(0, 100, 30, " %")
        labeled_row(g, 2, tr("sz.min_quality"), self.sz_minq, tr("sz.min_quality_tip"))
        self.sz_skip_larger = QCheckBox(tr("sz.skip_larger"))
        self.sz_skip_larger.setToolTip(tr("sz.skip_larger_tip"))
        g.addWidget(self.sz_skip_larger, 3, 0, 1, 2)
        card.body().addLayout(g)
        card.body().addWidget(hint(tr("sz.hint")))
        lay.addWidget(card)
        lay.addStretch(1)
        return page

    def _build_advanced_tab(self) -> QWidget:
        page, lay = _page()
        card = self._card(tr("adv.types"), "files")
        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(8)
        self.type_checks: dict[str, QCheckBox] = {}
        for i, key in enumerate(INPUT_GROUP_KEYS):
            cb = QCheckBox(tr(f"type.{key}"))
            cb.setToolTip(tr(f"type.{key}.tip"))
            if key == "heic" and not heif_available():
                cb.setEnabled(False)
                cb.setToolTip(tr("type.heic.unavailable"))
            self.type_checks[key] = cb
            grid.addWidget(cb, i // 3, i % 3)
        card.body().addLayout(grid)
        card.body().addWidget(hint(tr("adv.types_hint")))
        lay.addWidget(card)

        card = self._card(tr("adv.performance"), "gauge")
        g = form_grid()
        self.adv_workers = QSpinBox()
        self.adv_workers.setRange(0, 64)
        self.adv_workers.setSpecialValueText(tr("adv.workers_auto", n=cpu_count()))
        labeled_row(g, 0, tr("adv.workers"), self.adv_workers, tr("adv.workers_tip"))
        card.body().addLayout(g)
        lay.addWidget(card)

        card = self._card(tr("adv.after"), "check")
        self.adv_open = QCheckBox(tr("adv.open_output"))
        self.adv_notify = QCheckBox(tr("adv.notify"))
        card.body().addWidget(self.adv_open)
        card.body().addWidget(self.adv_notify)
        lay.addWidget(card)

        self.reset_btn = QPushButton(tr("adv.reset"))
        self.reset_btn.setObjectName("Danger")
        self.reset_btn.clicked.connect(self._reset_defaults)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self.reset_btn)
        lay.addLayout(row)
        lay.addStretch(1)
        return page

    # -------------------------------------------------------------- viselkedés
    def _connect_all(self) -> None:
        app_widgets = {*self.type_checks.values(), self.adv_workers, self.adv_open, self.adv_notify}
        for cb in self.type_checks.values():
            cb.toggled.connect(self._on_groups_change)
        self.adv_workers.valueChanged.connect(self._on_app_change)
        self.adv_open.toggled.connect(self._on_app_change)
        self.adv_notify.toggled.connect(self._on_app_change)
        for w in self.findChildren(QCheckBox):
            if w not in app_widgets:
                w.toggled.connect(self._on_change)
        for w in self.findChildren(QComboBox):
            w.currentIndexChanged.connect(self._on_change)
        for w in self.findChildren(QSpinBox):
            if w not in app_widgets:
                w.valueChanged.connect(self._on_change)
        for w in self.findChildren(QLineEdit):
            if w.parent() is not None and not isinstance(w.parent(), QSpinBox):
                w.textChanged.connect(self._on_change)

    def _on_change(self, *_args) -> None:
        self._update_dependent()
        if not self._loading:
            self.changed.emit()

    def _on_app_change(self, *_args) -> None:
        if not self._loading:
            self.app_options_changed.emit()

    def _on_groups_change(self, *_args) -> None:
        if not self._loading:
            self.app_options_changed.emit()
            self.groups_changed.emit()

    def _update_dependent(self) -> None:
        webp_on = self.chk_webp.isChecked()
        avif_on = self.chk_avif.isChecked()
        self.webp_card.setEnabled(webp_on)
        self.avif_card.setEnabled(avif_on)
        wl = self.webp_lossless.isChecked()
        self.webp_q_caption.setText(quality_caption(self.webp_q.value(), OutputFormat.WEBP, wl))
        self.webp_alpha.setEnabled(not wl)
        al = self.avif_lossless.isChecked()
        self.avif_q.setEnabled(not al)
        self.avif_sub.setEnabled(not al)
        self.avif_q_caption.setText(quality_caption(self.avif_q.value(), OutputFormat.AVIF, al))

        mode = _enum_data(self.rs_mode, ResizeMode)
        current = self._rs_pages[mode]
        self.rs_stack.setCurrentWidget(current)
        # a QStackedWidget a legnagyobb oldal magasságát foglalná – csak az aktuálisét kérjük
        for i in range(self.rs_stack.count()):
            page = self.rs_stack.widget(i)
            policy = QSizePolicy.Policy.Preferred if page is current else QSizePolicy.Policy.Ignored
            page.setSizePolicy(policy, policy)
        self.rs_stack.adjustSize()
        self.rs_upscale.setEnabled(mode is not ResizeMode.NONE)
        self.rs_sharpen_amount.setEnabled(self.rs_sharpen.isChecked())
        self._update_resize_example()

        self.md_gps.setEnabled(self.md_exif.isChecked())
        self.nm_lower.setEnabled(not self.nm_websafe.isChecked())
        target = self.sz_target.isChecked()
        self.sz_kb.setEnabled(target)
        self.sz_minq.setEnabled(target)
        self._update_name_example()

    def _update_resize_example(self) -> None:
        s = self.get_settings()
        examples = []
        for w, h in ((4000, 3000), (1200, 1600)):
            plan = plan_resize(w, h, s.resize)
            after = f"{plan.size[0]} × {plan.size[1]}" if plan else tr("rs.unchanged")
            examples.append(f"{w} × {h} → {after}")
        self.rs_example.setText(tr("rs.example") + "  " + "   ·   ".join(examples))

    def _update_name_example(self) -> None:
        s = self.get_settings()
        sample = Path(tr("nm.sample_name"))
        fmt = s.formats[0] if s.formats else OutputFormat.WEBP
        out = output_name(sample, fmt, s.naming)
        p = theme.current()
        self.nm_example.setText(
            f"{tr('nm.example')} <span style='color:{p.text}'>{sample.name}</span> → "
            f"<b style='color:{p.accent}'>{out}</b>"
        )

    def _reset_defaults(self) -> None:
        self.set_settings(ConversionSettings())
        self.changed.emit()

    def refresh_icons(self) -> None:
        for c in self._cards:
            c.refresh_icon()
        self._update_name_example()

    # --------------------------------------------------------------- get / set
    def get_settings(self) -> ConversionSettings:
        s = ConversionSettings()
        s.formats = [f for f, cb in ((OutputFormat.WEBP, self.chk_webp), (OutputFormat.AVIF, self.chk_avif)) if cb.isChecked()]
        s.keep_animation = self.chk_anim.isChecked()
        s.webp.quality = self.webp_q.value()
        s.webp.lossless = self.webp_lossless.isChecked()
        s.webp.method = self.webp_method.value()
        s.webp.alpha_quality = self.webp_alpha.value()
        s.webp.exact = self.webp_exact.isChecked()
        s.avif.quality = self.avif_q.value()
        s.avif.lossless = self.avif_lossless.isChecked()
        s.avif.speed = self.avif_speed.value()
        s.avif.subsampling = self.avif_sub.currentData()
        r = s.resize
        r.mode = _enum_data(self.rs_mode, ResizeMode)
        r.percent = self.rs_percent.value()
        r.long_edge = self.rs_long.value()
        if r.mode in (ResizeMode.FIT, ResizeMode.FILL):
            r.width, r.height = self.rs_box_w.value(), self.rs_box_h.value()
        else:
            r.width, r.height = self.rs_width.value(), self.rs_height.value()
        r.allow_upscale = self.rs_upscale.isChecked()
        r.resample = _enum_data(self.rs_filter, Resample)
        r.sharpen = self.rs_sharpen.isChecked()
        r.sharpen_amount = self.rs_sharpen_amount.value()
        m = s.metadata
        m.auto_orient = self.md_orient.isChecked()
        m.keep_exif = self.md_exif.isChecked()
        m.strip_gps = self.md_gps.isChecked()
        m.keep_xmp = self.md_xmp.isChecked()
        m.preserve_timestamps = self.md_times.isChecked()
        m.color_profile = _enum_data(self.md_color, ColorProfile)
        n = s.naming
        n.prefix = self.nm_prefix.text()
        n.suffix = self.nm_suffix.text()
        n.web_safe = self.nm_websafe.isChecked()
        n.lowercase = self.nm_lower.isChecked()
        n.conflict = _enum_data(self.nm_conflict, ConflictPolicy)
        s.target_size_enabled = self.sz_target.isChecked()
        s.target_size_kb = self.sz_kb.value()
        s.target_min_quality = self.sz_minq.value()
        s.skip_if_larger = self.sz_skip_larger.isChecked()
        return s.validate()

    def set_settings(self, s: ConversionSettings) -> None:
        self._loading = True
        try:
            self.chk_webp.setChecked(OutputFormat.WEBP in s.formats)
            self.chk_avif.setChecked(OutputFormat.AVIF in s.formats and self.chk_avif.isEnabled())
            self.chk_anim.setChecked(s.keep_animation)
            self.webp_q.setValue(s.webp.quality)
            self.webp_lossless.setChecked(s.webp.lossless)
            self.webp_method.setValue(s.webp.method)
            self.webp_alpha.setValue(s.webp.alpha_quality)
            self.webp_exact.setChecked(s.webp.exact)
            self.avif_q.setValue(s.avif.quality)
            self.avif_lossless.setChecked(s.avif.lossless)
            self.avif_speed.setValue(s.avif.speed)
            _set_combo(self.avif_sub, s.avif.subsampling)
            r = s.resize
            _set_combo(self.rs_mode, r.mode)
            self.rs_percent.setValue(r.percent)
            self.rs_width.setValue(r.width)
            self.rs_height.setValue(r.height)
            self.rs_box_w.setValue(r.width)
            self.rs_box_h.setValue(r.height)
            self.rs_long.setValue(r.long_edge)
            self.rs_upscale.setChecked(r.allow_upscale)
            _set_combo(self.rs_filter, r.resample)
            self.rs_sharpen.setChecked(r.sharpen)
            self.rs_sharpen_amount.setValue(r.sharpen_amount)
            m = s.metadata
            self.md_orient.setChecked(m.auto_orient)
            self.md_exif.setChecked(m.keep_exif)
            self.md_gps.setChecked(m.strip_gps)
            self.md_xmp.setChecked(m.keep_xmp)
            self.md_times.setChecked(m.preserve_timestamps)
            _set_combo(self.md_color, m.color_profile)
            n = s.naming
            self.nm_prefix.setText(n.prefix)
            self.nm_suffix.setText(n.suffix)
            self.nm_websafe.setChecked(n.web_safe)
            self.nm_lower.setChecked(n.lowercase)
            _set_combo(self.nm_conflict, n.conflict)
            self.sz_target.setChecked(s.target_size_enabled)
            self.sz_kb.setValue(s.target_size_kb)
            self.sz_minq.setValue(s.target_min_quality)
            self.sz_skip_larger.setChecked(s.skip_if_larger)
        finally:
            self._loading = False
        self._update_dependent()

    def groups(self) -> list[str]:
        return [k for k, cb in self.type_checks.items() if cb.isChecked() and cb.isEnabled()]

    def set_groups(self, groups: list[str]) -> None:
        self._loading = True
        for k, cb in self.type_checks.items():
            cb.setChecked(k in groups)
        self._loading = False

    def workers(self) -> int:
        return self.adv_workers.value()

    def set_workers(self, n: int) -> None:
        self._loading = True
        self.adv_workers.setValue(n)
        self._loading = False

    def set_after_options(self, open_output: bool, notify: bool) -> None:
        self._loading = True
        self.adv_open.setChecked(open_output)
        self.adv_notify.setChecked(notify)
        self._loading = False

    def set_quality(self, fmt: OutputFormat, q: int) -> None:
        (self.webp_q if fmt is OutputFormat.WEBP else self.avif_q).setValue(q)
