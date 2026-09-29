"""A főablak."""

from __future__ import annotations

import os
import random
import sys
import time
from pathlib import Path

from PySide6.QtCore import QByteArray, QDir, QElapsedTimer, QProcess, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QCloseEvent, QDesktopServices, QDragEnterEvent, QDropEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSplitter,
    QStackedLayout,
    QTableView,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .. import APP_NAME, __version__
from ..core.batch import BatchSummary, default_workers
from ..core.config import AppState, save_state
from ..core.formats import all_input_extensions, extensions_for_groups, output_available
from ..core.models import JobResult, Status
from ..core.naming import plan_jobs
from ..core.presets import Preset, builtin_presets
from ..core.report import write_csv
from ..core.scanner import SourceItem
from ..core.settings import ConversionSettings, OutputFormat, SourceOptions
from ..i18n import LANGUAGES, fmt_bytes, fmt_duration, fmt_percent, get_language, tr
from . import theme
from .dialogs import AboutDialog, EstimateDialog, SummaryDialog
from .file_model import COL_NAME, COL_SAVING, COL_STATUS, FileFilterProxy, FileRow, FileTableModel
from .preview import PreviewDialog
from .settings_panel import SettingsPanel
from .widgets import Card, PathPicker, hint
from .workers import ConversionController, EstimateWorker, ScanWorker

USER_PRESET_PREFIX = "user:"


class MainWindow(QMainWindow):
    def __init__(self, state: AppState):
        super().__init__()
        self.state = state
        self.setWindowTitle(f"{APP_NAME} {__version__}")
        self.setWindowIcon(theme.app_icon())
        self.setAcceptDrops(True)
        self.resize(1360, 860)
        self.setMinimumSize(1020, 640)

        self.model = FileTableModel(self)
        self.proxy = FileFilterProxy(self)
        self.proxy.setSourceModel(self.model)
        self.scanner = ScanWorker()
        self.scanner.items_found.connect(self._on_items_found)
        self.scanner.dims_ready.connect(self._on_dims_ready)
        self.scanner.progress.connect(self._on_scan_progress)
        self.scanner.finished.connect(self._on_scan_finished)
        self._listing = 0  # hány beolvasás nem adta még vissza a fájllistát
        self._scanned_input = ""
        self.controller = ConversionController()
        self.controller.job_started.connect(self._on_job_started)
        self.controller.job_finished.connect(self._on_job_finished)
        self.controller.all_finished.connect(self._on_all_finished)
        self.estimator = EstimateWorker()
        self.estimator.finished.connect(self._on_estimate)
        self.estimator.failed.connect(lambda msg: self._log(msg, "danger"))

        self._running = False
        self._paused = False
        self._elapsed = QElapsedTimer()
        self._done_count = 0
        self._total_count = 0
        self._run_bytes: dict = {}
        self._last_summary: BatchSummary | None = None
        self._run_output_dir = ""
        self._preset_dirty = False
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(800)
        self._save_timer.timeout.connect(self._save_state)
        self._rescan_timer = QTimer(self)
        self._rescan_timer.setSingleShot(True)
        self._rescan_timer.setInterval(350)
        self._rescan_timer.timeout.connect(self.rescan)
        self._tick = QTimer(self)
        self._tick.setInterval(1000)
        self._tick.timeout.connect(self._update_progress_labels)

        self._build_ui()
        self._build_shortcuts()
        self._apply_icons()
        self._load_state()
        self._update_buttons()

    # ================================================================ UI
    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("Root")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(14, 10, 14, 10)
        outer.setSpacing(10)
        outer.addLayout(self._build_header())

        self.h_split = QSplitter(Qt.Orientation.Horizontal)
        self.h_split.setChildrenCollapsible(False)
        self.h_split.setHandleWidth(10)

        left = QWidget()
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(0, 0, 0, 0)
        left_lay.setSpacing(10)
        left_lay.addWidget(self._build_folders_card())
        self.v_split = QSplitter(Qt.Orientation.Vertical)
        self.v_split.setChildrenCollapsible(True)
        self.v_split.setHandleWidth(10)
        self.v_split.addWidget(self._build_files_card())
        self.v_split.addWidget(self._build_log_card())
        self.v_split.setStretchFactor(0, 4)
        self.v_split.setStretchFactor(1, 1)
        self.v_split.setSizes([520, 150])
        left_lay.addWidget(self.v_split, 1)

        self.settings_panel = SettingsPanel()
        self.settings_panel.setMinimumWidth(400)
        self.settings_panel.changed.connect(self._on_settings_changed)
        self.settings_panel.app_options_changed.connect(self._schedule_save)
        self.settings_panel.groups_changed.connect(lambda: self._rescan_timer.start())

        self.h_split.addWidget(left)
        self.h_split.addWidget(self.settings_panel)
        self.h_split.setStretchFactor(0, 3)
        self.h_split.setStretchFactor(1, 2)
        self.h_split.setSizes([860, 460])
        outer.addWidget(self.h_split, 1)
        outer.addWidget(self._build_run_card())
        self.statusBar().showMessage(tr("status.ready"))

    def _build_header(self) -> QHBoxLayout:
        bar = QHBoxLayout()
        bar.setSpacing(10)
        logo = QLabel()
        logo.setPixmap(theme.logo_pixmap(34))
        title = QLabel(APP_NAME)
        title.setObjectName("AppTitle")
        ver = QLabel(f"v{__version__}")
        ver.setObjectName("Version")
        bar.addWidget(logo)
        bar.addWidget(title)
        bar.addWidget(ver)
        bar.addStretch(1)

        bar.addWidget(QLabel(tr("preset.label")))
        self.preset_combo = QComboBox()
        self.preset_combo.setMinimumWidth(270)
        self.preset_combo.setMaxVisibleItems(20)
        self.preset_combo.activated.connect(self._on_preset_selected)
        bar.addWidget(self.preset_combo)
        self.preset_save_btn = QToolButton()
        self.preset_save_btn.setToolTip(tr("preset.save"))
        self.preset_save_btn.clicked.connect(self._save_preset)
        self.preset_del_btn = QToolButton()
        self.preset_del_btn.setToolTip(tr("preset.delete"))
        self.preset_del_btn.clicked.connect(self._delete_preset)
        bar.addWidget(self.preset_save_btn)
        bar.addWidget(self.preset_del_btn)
        bar.addSpacing(12)

        self.lang_btn = QToolButton()
        self.lang_btn.setToolTip(tr("lang.tooltip"))
        self.lang_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.lang_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.lang_btn.setText(get_language().upper())
        menu = QMenu(self)
        for code, name in LANGUAGES.items():
            act = menu.addAction(name)
            act.setCheckable(True)
            act.setChecked(code == get_language())
            act.triggered.connect(lambda _=False, c=code: self._change_language(c))
        self.lang_btn.setMenu(menu)
        bar.addWidget(self.lang_btn)
        self.theme_btn = QToolButton()
        self.theme_btn.setToolTip(tr("theme.toggle"))
        self.theme_btn.clicked.connect(self._toggle_theme)
        bar.addWidget(self.theme_btn)
        self.about_btn = QToolButton()
        self.about_btn.setToolTip(tr("about.title") + " (F1)")
        self.about_btn.clicked.connect(self._show_about)
        bar.addWidget(self.about_btn)
        return bar

    def _build_folders_card(self) -> Card:
        card = Card(tr("folders.title"), icon_name="folder")
        self.folders_card = card
        grid = QVBoxLayout()
        grid.setSpacing(8)

        in_lbl = QLabel(tr("folders.input"))
        in_lbl.setObjectName("Muted")
        self.input_picker = PathPicker(tr("folders.choose_input"), "folder")
        self.input_picker.edit.setPlaceholderText(tr("folders.input_ph"))
        self.input_picker.pathChanged.connect(self._on_input_changed)
        grid.addWidget(in_lbl)
        grid.addWidget(self.input_picker)
        opts = QHBoxLayout()
        self.chk_recursive = QCheckBox(tr("folders.recursive"))
        self.chk_recursive.setToolTip(tr("folders.recursive_tip"))
        self.chk_recursive.toggled.connect(lambda _: self._rescan_timer.start())
        opts.addWidget(self.chk_recursive)
        opts.addStretch(1)
        grid.addLayout(opts)

        out_lbl = QLabel(tr("folders.output"))
        out_lbl.setObjectName("Muted")
        self.output_picker = PathPicker(tr("folders.choose_output"), "folder_out")
        self.output_picker.edit.setPlaceholderText(tr("folders.output_ph"))
        self.output_picker.pathChanged.connect(self._on_output_changed)
        grid.addWidget(out_lbl)
        grid.addWidget(self.output_picker)
        opts = QHBoxLayout()
        self.chk_structure = QCheckBox(tr("folders.keep_structure"))
        self.chk_structure.setToolTip(tr("folders.keep_structure_tip"))
        self.chk_structure.toggled.connect(self._schedule_save)
        self.chk_beside = QCheckBox(tr("folders.beside"))
        self.chk_beside.setToolTip(tr("folders.beside_tip"))
        self.chk_beside.toggled.connect(self._on_beside_toggled)
        opts.addWidget(self.chk_structure)
        opts.addWidget(self.chk_beside)
        opts.addStretch(1)
        grid.addLayout(opts)
        card.body().addLayout(grid)
        return card

    def _build_files_card(self) -> Card:
        card = Card(tr("files.title"), icon_name="list")
        self.files_card = card
        self.count_badge = QLabel("")
        self.count_badge.setObjectName("Badge")
        card.header.insertWidget(card.header.count() - 1, self.count_badge)

        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText(tr("files.filter_ph"))
        self.filter_edit.setClearButtonEnabled(True)
        self.filter_edit.setMaximumWidth(220)
        self.filter_edit.textChanged.connect(self.proxy.setFilterFixedString)
        self.status_filter = QComboBox()
        self.status_filter.addItem(tr("files.all_status"), None)
        for st in (Status.PENDING, Status.DONE, Status.SKIPPED, Status.FAILED):
            self.status_filter.addItem(tr(f"status.{st.value}"), st.value)
        self.status_filter.currentIndexChanged.connect(self._on_status_filter)
        card.header.addWidget(self.filter_edit)
        card.header.addWidget(self.status_filter)

        self.add_files_btn = QToolButton()
        self.add_files_btn.setToolTip(tr("files.add"))
        self.add_files_btn.clicked.connect(self._add_files)
        self.rescan_btn = QToolButton()
        self.rescan_btn.setToolTip(tr("files.rescan") + " (F5)")
        self.rescan_btn.clicked.connect(self.rescan)
        self.preview_btn = QToolButton()
        self.preview_btn.setToolTip(tr("files.preview") + " (Ctrl+P)")
        self.preview_btn.clicked.connect(self._open_preview)
        self.clear_btn = QToolButton()
        self.clear_btn.setToolTip(tr("files.clear"))
        self.clear_btn.clicked.connect(self._clear_list)
        for b in (self.preview_btn, self.add_files_btn, self.rescan_btn, self.clear_btn):
            card.header.addWidget(b)

        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setSortingEnabled(True)
        self.table.sortByColumn(COL_NAME, Qt.SortOrder.AscendingOrder)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        self.table.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(30)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._table_menu)
        self.table.doubleClicked.connect(lambda _idx: self._open_preview())
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(COL_NAME, QHeaderView.ResizeMode.Stretch)
        for col in range(1, self.model.columnCount()):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.Interactive)
        header.resizeSection(1, 64)
        header.resizeSection(2, 110)
        header.resizeSection(3, 84)
        header.resizeSection(COL_STATUS, 104)
        header.resizeSection(5, 84)
        header.resizeSection(6, 84)
        header.resizeSection(COL_SAVING, 96)
        header.setHighlightSections(False)

        self.drop_hint = QWidget()
        dh = QVBoxLayout(self.drop_hint)
        dh.addStretch(1)
        self.drop_icon = QLabel()
        self.drop_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        dh.addWidget(self.drop_icon)
        msg = QLabel(tr("files.drop_hint"))
        msg.setObjectName("DropHint")
        msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        dh.addWidget(msg)
        sub = hint(tr("files.drop_sub"))
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        dh.addWidget(sub)
        dh.addStretch(1)

        holder = QWidget()
        self.table_stack = QStackedLayout(holder)
        self.table_stack.addWidget(self.drop_hint)
        self.table_stack.addWidget(self.table)
        card.body().addWidget(holder, 1)
        card.body().setContentsMargins(10, 12, 10, 10)
        return card

    def _build_log_card(self) -> Card:
        card = Card(tr("log.title"), icon_name="list")
        self.log_card = card
        self.log_clear_btn = QToolButton()
        self.log_clear_btn.setToolTip(tr("log.clear"))
        card.header.addWidget(self.log_clear_btn)
        self.log_view = QPlainTextEdit()
        self.log_view.setObjectName("Log")
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(20000)
        self.log_clear_btn.clicked.connect(self.log_view.clear)
        card.body().addWidget(self.log_view)
        card.body().setContentsMargins(10, 10, 10, 10)
        return card

    def _build_run_card(self) -> Card:
        card = Card()
        lay = QHBoxLayout()
        lay.setSpacing(14)
        col = QVBoxLayout()
        col.setSpacing(6)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFormat("%p%")
        col.addWidget(self.progress)
        stats = QHBoxLayout()
        self.lbl_count = QLabel("")
        self.lbl_eta = QLabel("")
        self.lbl_eta.setObjectName("Muted")
        stats.addWidget(self.lbl_count)
        stats.addStretch(1)
        stats.addWidget(self.lbl_eta)
        col.addLayout(stats)
        lay.addLayout(col, 1)

        self.estimate_btn = QPushButton(tr("btn.estimate"))
        self.estimate_btn.setToolTip(tr("btn.estimate_tip"))
        self.estimate_btn.clicked.connect(self._estimate)
        self.open_out_btn = QPushButton(tr("btn.open_output"))
        self.open_out_btn.clicked.connect(self._open_output)
        self.export_btn = QPushButton(tr("btn.export"))
        self.export_btn.clicked.connect(self._export_report)
        self.pause_btn = QPushButton(tr("btn.pause"))
        self.pause_btn.clicked.connect(self._toggle_pause)
        self.stop_btn = QPushButton(tr("btn.stop"))
        self.stop_btn.setObjectName("Danger")
        self.stop_btn.clicked.connect(self._stop)
        self.start_btn = QPushButton(tr("btn.start"))
        self.start_btn.setObjectName("Primary")
        self.start_btn.setMinimumHeight(40)
        self.start_btn.setToolTip("Ctrl+Enter")
        self.start_btn.clicked.connect(self.start_conversion)
        for b in (self.estimate_btn, self.open_out_btn, self.export_btn, self.pause_btn, self.stop_btn):
            b.setMinimumHeight(40)
            lay.addWidget(b)
        lay.addWidget(self.start_btn)
        card.body().addLayout(lay)
        card.body().setContentsMargins(14, 10, 14, 10)
        return card

    def _build_shortcuts(self) -> None:
        QShortcut(QKeySequence("Ctrl+Return"), self, activated=self.start_conversion)
        QShortcut(QKeySequence("Ctrl+Enter"), self, activated=self.start_conversion)
        QShortcut(QKeySequence("Escape"), self, activated=self._stop)
        QShortcut(QKeySequence("F5"), self, activated=self.rescan)
        QShortcut(QKeySequence("Ctrl+P"), self, activated=self._open_preview)
        QShortcut(QKeySequence("Ctrl+O"), self, activated=self.input_picker.browse)
        QShortcut(QKeySequence("Ctrl+Shift+O"), self, activated=self.output_picker.browse)
        QShortcut(QKeySequence("F1"), self, activated=self._show_about)
        QShortcut(QKeySequence("Ctrl+F"), self, activated=lambda: self.filter_edit.setFocus())
        act = QAction(self)
        act.setShortcut(QKeySequence.StandardKey.SelectAll)
        act.triggered.connect(self.table.selectAll)
        self.table.addAction(act)

    def _apply_icons(self) -> None:
        dark = theme.current().name == "dark"
        self.theme_btn.setIcon(theme.icon("sun" if dark else "moon"))
        self.about_btn.setIcon(theme.icon("info"))
        self.lang_btn.setIcon(theme.icon("globe"))
        self.preset_save_btn.setIcon(theme.icon("save"))
        self.preset_del_btn.setIcon(theme.icon("trash"))
        self.add_files_btn.setIcon(theme.icon("plus"))
        self.rescan_btn.setIcon(theme.icon("refresh"))
        self.preview_btn.setIcon(theme.icon("eye"))
        self.clear_btn.setIcon(theme.icon("x"))
        self.log_clear_btn.setIcon(theme.icon("trash", "muted"))
        self.estimate_btn.setIcon(theme.icon("gauge"))
        self.open_out_btn.setIcon(theme.icon("external"))
        self.export_btn.setIcon(theme.icon("download"))
        self.pause_btn.setIcon(theme.icon("play" if self._paused else "pause"))
        self.stop_btn.setIcon(theme.icon("stop", "danger"))
        self.start_btn.setIcon(theme.icon("play", "white"))
        self.start_btn.setIconSize(QSize(16, 16))
        self.drop_icon.setPixmap(theme.icon("image", "muted", 56).pixmap(56, 56))
        for card in (self.folders_card, self.files_card, self.log_card):
            card.refresh_icon()
        self.input_picker.refresh_icons()
        self.output_picker.refresh_icons()
        self.settings_panel.refresh_icons()

    # ============================================================ állapot
    def _load_state(self) -> None:
        st = self.state
        self._refresh_presets()
        self.settings_panel.set_settings(st.conversion)
        self.settings_panel.set_groups(st.source.groups)
        self.settings_panel.set_workers(st.workers)
        self.settings_panel.set_after_options(st.open_output_when_done, st.notify_when_done)
        for chk, value in (
            (self.chk_recursive, st.source.recursive),
            (self.chk_structure, st.source.keep_structure),
            (self.chk_beside, st.source.beside_source),
        ):
            chk.blockSignals(True)
            chk.setChecked(value)
            chk.blockSignals(False)
        self.output_picker.setEnabled(not st.source.beside_source)
        self.chk_structure.setEnabled(not st.source.beside_source)
        self.input_picker.setRecent(st.recent_inputs)
        self.output_picker.setRecent(st.recent_outputs)
        self.output_picker.setPath(st.output_dir, emit=False)
        self.input_picker.setPath(st.input_dir, emit=False)
        self._select_preset_key(st.last_preset)
        if st.window_geometry:
            self.restoreGeometry(QByteArray.fromBase64(st.window_geometry.encode()))
        if st.splitter_state:
            try:
                h, v = st.splitter_state.split("|", 1)
                self.h_split.restoreState(QByteArray.fromBase64(h.encode()))
                self.v_split.restoreState(QByteArray.fromBase64(v.encode()))
            except ValueError:
                pass
        if st.input_dir and Path(st.input_dir).is_dir():
            QTimer.singleShot(0, self.rescan)
        self._update_counts()

    def _collect_state(self) -> None:
        st = self.state
        st.input_dir = self.input_picker.path()
        st.output_dir = self.output_picker.path()
        st.conversion = self.settings_panel.get_settings()
        st.source = self._source_options()
        st.workers = self.settings_panel.workers()
        st.open_output_when_done = self.settings_panel.adv_open.isChecked()
        st.notify_when_done = self.settings_panel.adv_notify.isChecked()
        st.last_preset = self._current_preset_key() or st.last_preset
        st.window_geometry = bytes(self.saveGeometry().toBase64()).decode()
        st.splitter_state = (
            bytes(self.h_split.saveState().toBase64()).decode() + "|" + bytes(self.v_split.saveState().toBase64()).decode()
        )

    def _save_state(self) -> None:
        self._collect_state()
        save_state(self.state)

    def _schedule_save(self, *_args) -> None:
        self._save_timer.start()

    def _source_options(self) -> SourceOptions:
        return SourceOptions(
            recursive=self.chk_recursive.isChecked(),
            groups=self.settings_panel.groups(),
            keep_structure=self.chk_structure.isChecked(),
            beside_source=self.chk_beside.isChecked(),
        ).validate()

    # ============================================================ presetek
    def _refresh_presets(self) -> None:
        self.preset_combo.blockSignals(True)
        self.preset_combo.clear()
        for p in builtin_presets():
            self.preset_combo.addItem(p.name, p.key)
            self.preset_combo.setItemData(self.preset_combo.count() - 1, p.description, Qt.ItemDataRole.ToolTipRole)
        if self.state.user_presets:
            self.preset_combo.insertSeparator(self.preset_combo.count())
            for name in sorted(self.state.user_presets, key=str.casefold):
                self.preset_combo.addItem(f"★ {name}", USER_PRESET_PREFIX + name)
        self.preset_combo.blockSignals(False)

    def _preset_by_key(self, key: str) -> Preset | None:
        if key.startswith(USER_PRESET_PREFIX):
            name = key[len(USER_PRESET_PREFIX):]
            data = self.state.user_presets.get(name)
            if data is None:
                return None
            return Preset(key, ConversionSettings.from_dict(data), builtin=False, custom_name=name)
        for p in builtin_presets():
            if p.key == key:
                return p
        return None

    def _current_preset_key(self) -> str | None:
        return self.preset_combo.currentData()

    def _select_preset_key(self, key: str) -> None:
        idx = self.preset_combo.findData(key)
        if idx >= 0:
            self.preset_combo.setCurrentIndex(idx)
            preset = self._preset_by_key(key)
            if preset is not None:
                self._preset_dirty = preset.settings.to_dict() != self.settings_panel.get_settings().to_dict()
        else:
            self._preset_dirty = True
        self._update_preset_label()

    def _update_preset_label(self) -> None:
        idx = self.preset_combo.currentIndex()
        key = self.preset_combo.currentData()
        preset = self._preset_by_key(key) if key else None
        if preset is None:
            return
        text = preset.name if preset.builtin else f"★ {preset.name}"
        if self._preset_dirty:
            text += "  " + tr("preset.modified")
        self.preset_combo.setItemText(idx, text)
        self.preset_del_btn.setEnabled(not preset.builtin)

    def _on_preset_selected(self, idx: int) -> None:
        # a korábbi elem "módosítva" jelölésének visszaállítása
        self._refresh_presets()
        self.preset_combo.setCurrentIndex(idx)
        preset = self._preset_by_key(self.preset_combo.currentData())
        if preset is None:
            return
        self.settings_panel.set_settings(preset.settings)
        self._preset_dirty = False
        self._update_preset_label()
        self._log(tr("log.preset_applied", name=preset.name))
        self._schedule_save()

    def _on_settings_changed(self) -> None:
        if not self._preset_dirty:
            self._preset_dirty = True
            self._update_preset_label()
        self._schedule_save()

    def _save_preset(self) -> None:
        current = self._preset_by_key(self._current_preset_key() or "")
        default = current.custom_name if current and not current.builtin else ""
        name, ok = QInputDialog.getText(self, tr("preset.save"), tr("preset.name_prompt"), text=default)
        name = name.strip()
        if not ok or not name:
            return
        if name in self.state.user_presets and name != default:
            if QMessageBox.question(self, tr("preset.save"), tr("preset.overwrite", name=name)) != QMessageBox.StandardButton.Yes:
                return
        self.state.user_presets[name] = self.settings_panel.get_settings().to_dict()
        self._refresh_presets()
        self._select_preset_key(USER_PRESET_PREFIX + name)
        self._preset_dirty = False
        self._update_preset_label()
        self._log(tr("log.preset_saved", name=name))
        self._save_state()

    def _delete_preset(self) -> None:
        key = self._current_preset_key() or ""
        if not key.startswith(USER_PRESET_PREFIX):
            return
        name = key[len(USER_PRESET_PREFIX):]
        if QMessageBox.question(self, tr("preset.delete"), tr("preset.delete_confirm", name=name)) != QMessageBox.StandardButton.Yes:
            return
        self.state.user_presets.pop(name, None)
        self._refresh_presets()
        self._select_preset_key("balanced")
        self._save_state()

    # ============================================================ mappák
    def _on_input_changed(self, path: str) -> None:
        if path and Path(path).is_dir():
            self.state.remember("recent_inputs", path)
            self.input_picker.setRecent(self.state.recent_inputs)
            if not self.output_picker.path() and not self.chk_beside.isChecked():
                p = Path(path)
                suggestion = p.parent / f"{p.name}_web"
                self.output_picker.setPath(QDir.toNativeSeparators(str(suggestion)))
                self._log(tr("log.output_suggested", path=suggestion))
        self.rescan()
        self._schedule_save()

    def _on_output_changed(self, path: str) -> None:
        if path:
            self.state.remember("recent_outputs", path)
            self.output_picker.setRecent(self.state.recent_outputs)
        inp = self.input_picker.path()
        if path and inp and self._is_inside(Path(path), Path(inp)):
            self._rescan_timer.start()
        self._schedule_save()

    def _on_beside_toggled(self, on: bool) -> None:
        self.output_picker.setEnabled(not on)
        self.chk_structure.setEnabled(not on)
        self._schedule_save()

    @staticmethod
    def _is_inside(child: Path, parent: Path) -> bool:
        try:
            child.resolve().relative_to(parent.resolve())
            return True
        except (ValueError, OSError):
            return False

    def _exclude_dirs(self) -> list[Path]:
        out = self.output_picker.path()
        return [Path(out)] if out and not self.chk_beside.isChecked() else []

    # ============================================================ fájllista
    def rescan(self) -> None:
        if self._running:
            return
        path = self.input_picker.path()
        # Ugyanannak a mappának az újraolvasásakor a kézzel hozzáadott fájlok
        # megmaradnak; új bemeneti mappánál tiszta lappal indulunk.
        same_input = bool(path) and path == self._scanned_input
        extra_rows = [r for r in self.model.rows if same_input and not self._from_input(r.item)]
        for r in extra_rows:
            r.status, r.result = Status.PENDING, None
        self._scanned_input = path
        self.model.set_rows(extra_rows)
        self._last_summary = None
        self._reset_progress()
        if not path:
            self.scanner.stop()
            self._listing = 0
            self._update_counts()
            return
        p = Path(path)
        if not p.is_dir():
            self.scanner.stop()
            self._listing = 0
            self.statusBar().showMessage(tr("status.input_missing", path=path), 6000)
            self._update_counts()
            return
        exts = extensions_for_groups(self.settings_panel.groups())
        self.statusBar().showMessage(tr("status.scanning"))
        self._listing = 1
        self.scanner.start([p], exts, self.chk_recursive.isChecked(), self._exclude_dirs(), replace=True)
        self._update_counts()

    def _from_input(self, item: SourceItem) -> bool:
        inp = self.input_picker.path()
        return bool(inp) and os.path.normcase(str(item.base)) == os.path.normcase(str(Path(inp)))

    def _add_paths(self, paths: list[Path]) -> None:
        if not paths:
            return
        exts = extensions_for_groups(self.settings_panel.groups()) or all_input_extensions()
        self._listing += 1
        self.scanner.start(paths, exts, self.chk_recursive.isChecked(), self._exclude_dirs(), replace=False)
        self._update_buttons()

    def _on_items_found(self, gen: int, items: list, replace: bool) -> None:
        if gen != self.scanner.generation:
            return
        self._listing = max(0, self._listing - 1)
        added = self.model.append_rows([FileRow(i) for i in items])
        if not replace:
            self._log(tr("log.files_added", n=len(added)))
        self._update_counts()

    def _on_dims_ready(self, gen: int, updates: list) -> None:
        if gen == self.scanner.generation:
            self.model.set_dims(updates)

    def _on_scan_progress(self, gen: int, done: int, total: int) -> None:
        if gen == self.scanner.generation and total:
            self.statusBar().showMessage(tr("status.reading", done=done, total=total))

    def _on_scan_finished(self, gen: int, replace: bool) -> None:
        if gen != self.scanner.generation:
            return
        n, size, _, _ = self.model.totals()
        self.statusBar().showMessage(tr("status.found", n=n, size=fmt_bytes(size)), 8000)
        if replace:
            self._log(tr("log.scanned", n=n, size=fmt_bytes(size), path=self.input_picker.path()))
        self._update_buttons()

    def _add_files(self) -> None:
        patterns = " ".join(f"*{e}" for e in sorted(all_input_extensions()))
        files, _ = QFileDialog.getOpenFileNames(
            self, tr("files.add"), self.input_picker.path() or str(Path.home()), f"{tr('files.images')} ({patterns})"
        )
        if files:
            self._add_paths([Path(f) for f in files])

    def _clear_list(self) -> None:
        if self._running:
            return
        self.scanner.stop()
        self._listing = 0
        self.model.clear()
        self._last_summary = None
        self._reset_progress()
        self._update_counts()

    def _on_status_filter(self) -> None:
        value = self.status_filter.currentData()
        self.proxy.set_status_filter(Status(value) if value else None)

    def _update_counts(self) -> None:
        n, size, checked, checked_size = self.model.totals()
        if n == 0:
            self.count_badge.setText(tr("files.none"))
            self.table_stack.setCurrentWidget(self.drop_hint)
        else:
            self.table_stack.setCurrentWidget(self.table)
            if checked == n:
                self.count_badge.setText(tr("files.count", n=n, size=fmt_bytes(size)))
            else:
                self.count_badge.setText(
                    tr("files.count_checked", c=checked, n=n, size=fmt_bytes(checked_size))
                )
        if not self._running:
            self.lbl_count.setText(tr("run.ready", n=checked) if n else "")
        self._update_buttons()

    def _selected_source_rows(self) -> list[int]:
        rows = {self.proxy.mapToSource(i).row() for i in self.table.selectionModel().selectedRows()}
        return sorted(rows)

    def _table_menu(self, pos) -> None:
        rows = self._selected_source_rows()
        menu = QMenu(self)
        a_prev = menu.addAction(theme.icon("eye"), tr("menu.preview"))
        a_prev.setEnabled(bool(rows))
        a_open = menu.addAction(theme.icon("image"), tr("menu.open_file"))
        a_open.setEnabled(len(rows) == 1)
        a_dir = menu.addAction(theme.icon("folder"), tr("menu.open_folder"))
        a_dir.setEnabled(len(rows) == 1)
        a_out = menu.addAction(theme.icon("external"), tr("menu.open_result"))
        res_row = self.model.rows[rows[0]] if len(rows) == 1 else None
        a_out.setEnabled(bool(res_row and res_row.result and res_row.result.written))
        menu.addSeparator()
        a_check = menu.addAction(theme.icon("check_all"), tr("menu.check_selected"))
        a_uncheck = menu.addAction(theme.icon("square"), tr("menu.uncheck_selected"))
        a_all = menu.addAction(tr("menu.check_all"))
        a_none = menu.addAction(tr("menu.check_none"))
        a_failed = menu.addAction(tr("menu.check_failed"))
        menu.addSeparator()
        a_remove = menu.addAction(theme.icon("trash"), tr("menu.remove"))
        a_remove.setEnabled(bool(rows) and not self._running)
        chosen = menu.exec(self.table.viewport().mapToGlobal(pos))
        if chosen is None:
            return
        if chosen is a_prev:
            self._open_preview()
        elif chosen is a_open:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.model.rows[rows[0]].item.path)))
        elif chosen is a_dir:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.model.rows[rows[0]].item.path.parent)))
        elif chosen is a_out and res_row and res_row.result:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(res_row.result.written[0].dest)))
        elif chosen is a_check:
            self.model.set_checked(rows, True)
        elif chosen is a_uncheck:
            self.model.set_checked(rows, False)
        elif chosen is a_all:
            self.model.set_checked(None, True)
        elif chosen is a_none:
            self.model.set_checked(None, False)
        elif chosen is a_failed:
            failed = [i for i, r in enumerate(self.model.rows) if r.status is Status.FAILED]
            self.model.set_checked(None, False)
            self.model.set_checked(failed, True)
        elif chosen is a_remove:
            self.model.remove_rows(rows)
        self._update_counts()

    # ============================================================ előnézet
    def _open_preview(self) -> None:
        if not self.model.rows:
            return
        visible = [self.proxy.mapToSource(self.proxy.index(r, 0)).row() for r in range(self.proxy.rowCount())]
        if not visible:
            return
        selected = self._selected_source_rows()
        start_row = selected[0] if selected else visible[0]
        paths = [self.model.rows[i].item.path for i in visible]
        start = visible.index(start_row) if start_row in visible else 0
        dlg = PreviewDialog(paths, start, self.settings_panel.get_settings(), self)
        dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dlg.apply_quality.connect(self._apply_preview_quality)
        dlg.show()

    def _apply_preview_quality(self, fmt, q: int) -> None:
        fmt = OutputFormat(fmt)
        self.settings_panel.set_quality(fmt, q)
        self._log(tr("log.quality_applied", fmt=fmt.value.upper(), q=q))

    # ============================================================ becslés
    def _estimate(self) -> None:
        if self.estimator.running or self._running:
            return
        rows = [self.model.rows[i] for i in self.model.checked_indices()]
        if not rows:
            return
        settings = self.settings_panel.get_settings()
        if not settings.formats:
            QMessageBox.warning(self, APP_NAME, tr("err.no_format"))
            return
        sample_n = min(len(rows), 8)
        # egyenletes mintavétel a méret szerint rendezett listából
        by_size = sorted(rows, key=lambda r: r.item.size)
        step = len(by_size) / sample_n
        sample = [by_size[int(i * step)].item for i in range(sample_n)]
        random.shuffle(sample)
        total = sum(r.item.size for r in rows)
        self.estimate_btn.setEnabled(False)
        self.estimate_btn.setText(tr("btn.estimating"))
        self.estimator.start(sample, settings, total, len(rows))

    def _on_estimate(self, result) -> None:
        self.estimate_btn.setText(tr("btn.estimate"))
        self._update_buttons()
        EstimateDialog(result, self).exec()

    # ============================================================ futtatás
    def start_conversion(self) -> None:
        if self._running:
            return
        settings = self.settings_panel.get_settings()
        src = self._source_options()
        if not settings.formats:
            QMessageBox.warning(self, APP_NAME, tr("err.no_format"))
            return
        for fmt in settings.formats:
            if not output_available(fmt):
                QMessageBox.critical(self, APP_NAME, tr("err.format_unavailable", fmt=fmt.value.upper()))
                return
        if self._listing:
            return  # a fájllista még épül
        indices = self.model.checked_indices()
        if not indices:
            QMessageBox.information(self, APP_NAME, tr("err.no_files"))
            return
        out_dir: Path | None = None
        if not src.beside_source:
            out_text = self.output_picker.path()
            if not out_text:
                QMessageBox.warning(self, APP_NAME, tr("err.no_output"))
                self.output_picker.edit.setFocus()
                return
            out_dir = Path(out_text)
            try:
                out_dir.mkdir(parents=True, exist_ok=True)
                probe = out_dir / ".webkep-write-test"
                probe.write_bytes(b"")
                probe.unlink()
            except OSError as exc:
                QMessageBox.critical(self, APP_NAME, tr("err.output_not_writable", path=out_dir, err=exc))
                return
            out_dir = out_dir.resolve()
            # a kimeneti mappában lévő (korábbi eredmény) fájlokat nem dolgozzuk fel újra
            indices = [i for i in indices if not self._is_inside(self.model.rows[i].item.path, out_dir)]
            if not indices:
                QMessageBox.information(self, APP_NAME, tr("err.no_files"))
                return

        items = [self.model.rows[i].item for i in indices]
        jobs = plan_jobs(items, settings, out_dir, src, indices)
        self.model.reset_results(indices)
        self._save_state()

        self._running = True
        self._paused = False
        self._done_count = 0
        self._total_count = len(jobs)
        self._run_bytes = {}
        self._run_output_dir = str(out_dir) if out_dir else str(items[0].path.parent)
        self.progress.setRange(0, len(jobs))
        self.progress.setValue(0)
        self._elapsed.start()
        self._tick.start()
        workers = self.settings_panel.workers() or default_workers()
        fmts = " + ".join(f.value.upper() for f in settings.formats)
        self._log(tr("log.start", n=len(jobs), fmts=fmts, workers=workers), "accent")
        if settings.target_size_enabled:
            self._log(tr("log.target_mode", kb=settings.target_size_kb))
        self.controller.start(jobs, settings, workers)
        self._set_locked(True)
        self._update_buttons()
        self._update_progress_labels()

    def _on_job_started(self, index: int) -> None:
        self.model.set_status(index, Status.RUNNING)

    def _on_job_finished(self, result: JobResult) -> None:
        if result.index < 0:
            self._log(result.error, "danger")
            return
        self.model.set_result(result.index, result)
        self._done_count += 1
        self.progress.setValue(self._done_count)
        for t in result.written:
            agg = self._run_bytes.setdefault(t.fmt, [0, 0])
            agg[0] += result.source_size
            agg[1] += t.size
        self._log_result(result)
        self._update_progress_labels()

    def _log_result(self, r: JobResult) -> None:
        name = str(self.model.rows[r.index].item.rel_path) if r.index < len(self.model.rows) else r.source.name
        if r.status is Status.FAILED:
            reason = r.error or "; ".join(t.note for t in r.targets if t.note)
            self._log(f"✗ {name}: {reason}", "danger")
            return
        if r.status is Status.CANCELLED:
            return
        parts = []
        for t in r.targets:
            if t.status is Status.DONE:
                change = fmt_percent(1 - t.size / r.source_size, 0, signed=True) if r.source_size else ""
                extra = f", {t.note}" if t.note else ""
                parts.append(f"{t.fmt.value.upper()} {fmt_bytes(t.size)} ({change}{extra})")
            elif t.status is Status.SKIPPED:
                parts.append(f"{t.fmt.value.upper()}: {tr('status.skipped').lower()} – {t.note}")
            elif t.status is Status.FAILED:
                parts.append(f"{t.fmt.value.upper()}: ✗ {t.note}")
        level = "warning" if r.status is Status.SKIPPED or any(t.status is Status.FAILED for t in r.targets) else "text"
        mark = "✓" if r.status is Status.DONE else "•"
        self._log(f"{mark} {name} → " + " · ".join(parts), level)
        for w in r.warnings:
            self._log(f"  ⚠ {name}: {w}", "warning")

    def _update_progress_labels(self) -> None:
        if not self._running:
            return
        done, total = self._done_count, self._total_count
        elapsed = self._elapsed.elapsed() / 1000
        self.lbl_count.setText(tr("run.progress", done=done, total=total))
        parts = []
        for fmt, (src, out) in self._run_bytes.items():
            saving = 1 - out / src if src else 0
            parts.append(f"{fmt.value.upper()}: {fmt_bytes(src)} → {fmt_bytes(out)} ({fmt_percent(saving, 0, signed=True)})")
        self._set_progress_text(parts)
        if self._paused:
            self.lbl_eta.setText(tr("run.paused"))
        elif done:
            rate = done / elapsed if elapsed else 0
            eta = (total - done) / rate if rate else 0
            self.lbl_eta.setText(
                tr("run.eta", elapsed=fmt_duration(elapsed), eta=fmt_duration(eta), rate=f"{rate:.1f}".replace(".", tr("decimal_sep")))
            )
        else:
            self.lbl_eta.setText(tr("run.elapsed", elapsed=fmt_duration(elapsed)))
        self.setWindowTitle(f"{round(done / total * 100) if total else 0}% – {APP_NAME}")

    def _on_all_finished(self, summary: BatchSummary) -> None:
        self._running = False
        self._paused = False
        self._tick.stop()
        self._last_summary = summary
        self._set_locked(False)
        self.setWindowTitle(f"{APP_NAME} {__version__}")
        self._update_progress_labels_final(summary)
        key = "log.finished_cancelled" if summary.was_cancelled else "log.finished"
        self._log(
            tr(key, done=summary.done, skipped=summary.skipped, failed=summary.failed, time=fmt_duration(summary.elapsed)),
            "success" if not summary.failed and not summary.was_cancelled else "warning",
        )
        self._update_buttons()
        QApplication.alert(self)
        if self.settings_panel.adv_open.isChecked() and summary.files_written and not summary.was_cancelled:
            self._open_output()
        if self.settings_panel.adv_notify.isChecked():
            dlg = SummaryDialog(summary, self._run_output_dir, self)
            dlg.exec()
            if dlg.export_requested:
                self._export_report()

    def _update_progress_labels_final(self, summary: BatchSummary) -> None:
        self.lbl_count.setText(
            tr("run.summary", done=summary.done, skipped=summary.skipped, failed=summary.failed)
        )
        parts = []
        for fmt, (src, out, _n) in summary.per_format.items():
            parts.append(
                f"{fmt.value.upper()}: {fmt_bytes(src)} → {fmt_bytes(out)} "
                f"({fmt_percent(summary.format_saving(fmt) or 0, 1, signed=True)})"
            )
        self._set_progress_text(parts)
        self.lbl_eta.setText(tr("run.total_time", time=fmt_duration(summary.elapsed)))

    def _set_progress_text(self, parts: list[str]) -> None:
        text = "%p%" + ("   ·   " + "   ·   ".join(parts) if parts else "")
        self.progress.setFormat(text.replace("%", "%%").replace("%%p%%", "%p%"))

    def _reset_progress(self) -> None:
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFormat("%p%")
        self.lbl_eta.setText("")

    def _toggle_pause(self) -> None:
        if not self._running:
            return
        self._paused = not self._paused
        if self._paused:
            self.controller.pause()
            self._log(tr("log.paused"), "warning")
        else:
            self.controller.resume()
            self._log(tr("log.resumed"))
        self._update_buttons()
        self._update_progress_labels()

    def _stop(self) -> None:
        if not self._running:
            return
        self.controller.cancel()
        self.stop_btn.setEnabled(False)
        self.pause_btn.setEnabled(False)
        self._log(tr("log.stopping"), "warning")

    def _set_locked(self, locked: bool) -> None:
        for w in (
            self.settings_panel,
            self.input_picker,
            self.chk_recursive,
            self.chk_structure,
            self.chk_beside,
            self.preset_combo,
            self.preset_save_btn,
            self.preset_del_btn,
            self.add_files_btn,
            self.rescan_btn,
            self.clear_btn,
            self.lang_btn,
        ):
            w.setEnabled(not locked)
        self.output_picker.setEnabled(not locked and not self.chk_beside.isChecked())
        if not locked:
            self.chk_structure.setEnabled(not self.chk_beside.isChecked())
            self._update_preset_label()

    def _update_buttons(self) -> None:
        has_files = bool(self.model.checked_indices())
        running = self._running
        self.start_btn.setEnabled(has_files and not running and not self._listing)
        self.start_btn.setText(tr("btn.running") if running else tr("btn.start"))
        self.pause_btn.setEnabled(running)
        self.pause_btn.setText(tr("btn.resume") if self._paused else tr("btn.pause"))
        self.pause_btn.setIcon(theme.icon("play" if self._paused else "pause"))
        self.stop_btn.setEnabled(running)
        self.estimate_btn.setEnabled(has_files and not running and not self.estimator.running)
        self.export_btn.setEnabled(self._last_summary is not None and not running)
        out = self._run_output_dir or self.output_picker.path()
        self.open_out_btn.setEnabled(bool(out) and Path(out).is_dir())
        self.preview_btn.setEnabled(bool(self.model.rows))

    # ============================================================ egyéb
    def _open_output(self) -> None:
        out = self._run_output_dir or self.output_picker.path()
        if out and Path(out).is_dir():
            QDesktopServices.openUrl(QUrl.fromLocalFile(out))

    def _export_report(self) -> None:
        if not self._last_summary:
            return
        stamp = time.strftime("%Y%m%d-%H%M%S")
        start_dir = self._run_output_dir or str(Path.home())
        path, _ = QFileDialog.getSaveFileName(
            self, tr("btn.export"), str(Path(start_dir) / f"webkep-riport-{stamp}.csv"), "CSV (*.csv)"
        )
        if not path:
            return
        try:
            rows = write_csv(self._last_summary.results, path)
            self._log(tr("log.report_saved", path=path, n=rows), "success")
        except OSError as exc:
            QMessageBox.critical(self, APP_NAME, str(exc))

    def _log(self, text: str, level: str = "text") -> None:
        p = theme.current()
        color = {
            "text": p.text,
            "muted": p.muted,
            "accent": p.accent,
            "success": p.success,
            "warning": p.warning,
            "danger": p.danger,
        }.get(level, p.text)
        stamp = time.strftime("%H:%M:%S")
        safe = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        self.log_view.appendHtml(
            f"<span style='color:{p.muted}'>{stamp}</span>&nbsp;&nbsp;<span style='color:{color}'>{safe}</span>"
        )

    def _toggle_theme(self) -> None:
        new = "light" if theme.current().name == "dark" else "dark"
        theme.apply_theme(QApplication.instance(), new)
        self.state.theme = new
        self._apply_icons()
        self.model.refresh_all()
        self._schedule_save()

    def _change_language(self, code: str) -> None:
        if code == get_language():
            return
        self.state.language = code
        self._save_state()
        box = QMessageBox(self)
        box.setWindowTitle(APP_NAME)
        box.setText(tr("lang.restart"))
        restart = box.addButton(tr("lang.restart_now"), QMessageBox.ButtonRole.AcceptRole)
        box.addButton(tr("lang.later"), QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is restart:
            if getattr(sys, "frozen", False):
                QProcess.startDetached(sys.executable, sys.argv[1:])
            else:
                QProcess.startDetached(sys.executable, ["-m", "webkep"])
            self.close()

    def _show_about(self) -> None:
        AboutDialog(self).exec()

    # ============================================================ drag & drop
    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if not self._running and event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        paths = [Path(u.toLocalFile()) for u in event.mimeData().urls() if u.isLocalFile()]
        if not paths:
            return
        event.acceptProposedAction()
        if len(paths) == 1 and paths[0].is_dir() and not self.model.rows:
            self.input_picker.setPath(QDir.toNativeSeparators(str(paths[0])))
        else:
            self._add_paths(paths)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if self._running:
            answer = QMessageBox.question(self, APP_NAME, tr("close.running"))
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self.controller.cancel()
            deadline = time.monotonic() + 30
            while self.controller.running and time.monotonic() < deadline:
                QApplication.processEvents()
                self.controller.wait(0.05)
        self.scanner.stop()
        self._save_state()
        super().closeEvent(event)
