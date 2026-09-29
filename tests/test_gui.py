"""A grafikus felület füstpróbái (képernyő nélkül, offscreen módban)."""

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from webkep.core.config import AppState  # noqa: E402
from webkep.core.models import Status  # noqa: E402
from webkep.core.settings import ConversionSettings, OutputFormat, ResizeMode  # noqa: E402

from .conftest import photo  # noqa: E402


@pytest.fixture
def window(qtbot, tmp_path):
    from webkep.gui import theme
    from webkep.gui.main_window import MainWindow

    src = tmp_path / "Képek"
    (src / "al mappa").mkdir(parents=True)
    photo((400, 300)).save(src / "egy.jpg", quality=90)
    photo((300, 300)).save(src / "al mappa" / "kettő.png")
    photo((200, 100)).convert("RGBA").save(src / "három.png")
    state = AppState(input_dir=str(src), output_dir=str(tmp_path / "Kimenet"))
    state.notify_when_done = False
    theme.apply_theme(qtbot_app(), "dark")
    win = MainWindow(state)
    qtbot.addWidget(win)
    win.show()
    qtbot.waitUntil(lambda: len(win.model.rows) == 3, timeout=10000)
    qtbot.waitUntil(lambda: all(r.dims for r in win.model.rows), timeout=10000)
    return win


def qtbot_app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance()


def test_scan_and_convert(window, qtbot, tmp_path):
    panel = window.settings_panel
    panel.chk_avif.setChecked(True)
    assert panel.get_settings().formats == [OutputFormat.WEBP, OutputFormat.AVIF]
    window.start_conversion()
    assert window._running
    qtbot.waitUntil(lambda: not window._running, timeout=60000)
    out = tmp_path / "Kimenet"
    assert (out / "egy.webp").exists() and (out / "egy.avif").exists()
    assert (out / "al mappa" / "kettő.webp").exists()
    assert all(r.status is Status.DONE for r in window.model.rows)
    assert window.export_btn.isEnabled()
    report = tmp_path / "r.csv"
    from webkep.core.report import write_csv

    assert write_csv(window._last_summary.results, report) == 6


def test_unchecked_rows_are_skipped(window, qtbot, tmp_path):
    window.model.set_checked([0], False)
    window.start_conversion()
    qtbot.waitUntil(lambda: not window._running, timeout=60000)
    statuses = [r.status for r in window.model.rows]
    assert statuses.count(Status.DONE) == 2
    assert statuses.count(Status.PENDING) == 1


def test_settings_panel_roundtrip(window):
    panel = window.settings_panel
    s = ConversionSettings(formats=[OutputFormat.AVIF])
    s.avif.quality = 42
    s.resize.mode = ResizeMode.FILL
    s.resize.width, s.resize.height = 320, 240
    s.naming.suffix = "-web"
    s.target_size_enabled = True
    panel.set_settings(s)
    got = panel.get_settings()
    assert got.to_dict() == s.validate().to_dict()
    assert "-web" in panel.nm_example.text()


def test_presets_apply_and_mark_modified(window):
    combo = window.preset_combo
    idx = combo.findData("thumbnail")
    combo.setCurrentIndex(idx)
    window._on_preset_selected(idx)
    s = window.settings_panel.get_settings()
    assert s.resize.mode is ResizeMode.FILL and s.naming.suffix == "-thumb"
    assert not window._preset_dirty
    window.settings_panel.webp_q.setValue(33)
    assert window._preset_dirty
    assert "módosítva" in combo.itemText(combo.currentIndex())


def test_status_filter_and_text_filter(window, qtbot):
    window.filter_edit.setText("egy")
    assert window.proxy.rowCount() == 1
    window.filter_edit.clear()
    idx = window.status_filter.findData(Status.DONE.value)
    window.status_filter.setCurrentIndex(idx)
    assert window.proxy.rowCount() == 0
    window.status_filter.setCurrentIndex(0)
    assert window.proxy.rowCount() == 3


def test_theme_toggle_and_state_save(window, tmp_path):
    window._toggle_theme()
    from webkep.gui import theme

    assert theme.current().name == "light"
    window._save_state()
    from webkep.core.config import load_state

    loaded = load_state()
    assert loaded.theme == "light"
    assert Path(loaded.input_dir).name == "Képek"
    window._toggle_theme()


def test_preview_dialog(window, qtbot):
    from webkep.gui.preview import PreviewDialog

    paths = [r.item.path for r in window.model.rows]
    dlg = PreviewDialog(paths, 0, window.settings_panel.get_settings(), window)
    qtbot.addWidget(dlg)
    dlg.show()
    qtbot.waitUntil(lambda: dlg.right.has_image(), timeout=15000)
    assert "KB" in dlg.right_info.text() or "B" in dlg.right_info.text()
    applied = []
    dlg.apply_quality.connect(lambda fmt, q: applied.append((fmt, q)))
    dlg.quality.setValue(55)
    dlg._apply()
    assert applied == [("webp", 55)]
    dlg._step(1)
    qtbot.waitUntil(lambda: dlg.right.has_image() and dlg.index == 1, timeout=15000)
    dlg.close()


def test_estimate(window, qtbot):
    results = []
    window.estimator.finished.disconnect(window._on_estimate)  # a modális ablak blokkolná a tesztet
    window.estimator.finished.connect(results.append)
    rows = window.model.rows
    window.estimator.start([r.item for r in rows], window.settings_panel.get_settings(), 1000, 3)
    qtbot.waitUntil(lambda: bool(results), timeout=30000)
    assert OutputFormat.WEBP in results[0].formats


def test_stylesheet_parses_with_spaces_and_accents(qtbot, tmp_path, monkeypatch):
    """Regresszió: a téma képhivatkozásai szóközös/ékezetes útvonalon is működjenek."""
    from PySide6.QtCore import qInstallMessageHandler
    from PySide6.QtWidgets import QCheckBox

    from webkep.gui import theme

    weird = tmp_path / "Kovács Béla temp"
    weird.mkdir()
    monkeypatch.setenv("TMPDIR", str(weird))
    monkeypatch.setenv("TEMP", str(weird))
    monkeypatch.setenv("TMP", str(weird))
    monkeypatch.setattr(theme, "_asset_dir", None)
    app = qtbot_app()
    old_name = app.applicationName()
    app.setApplicationName("WebKép Konverter")
    messages = []
    previous = qInstallMessageHandler(lambda _m, _c, text: messages.append(text))
    try:
        theme.apply_theme(app, "light")
        cb = QCheckBox("x")
        qtbot.addWidget(cb)
        cb.setChecked(True)
        cb.show()
        app.processEvents()
    finally:
        qInstallMessageHandler(previous)
        app.setApplicationName(old_name)
        theme.apply_theme(app, "dark")
    assert not [m for m in messages if "parse" in m.lower()]


def test_add_files_during_rescan_keeps_everything(window, qtbot, tmp_path):
    extra_dir = tmp_path / "extra"
    extra_dir.mkdir()
    photo((120, 90)).save(extra_dir / "plusz.jpg")
    photo((120, 90)).save(extra_dir / "plusz2.png")
    window.rescan()
    assert not window.start_btn.isEnabled()  # a lista még épül
    window._add_paths([extra_dir])
    qtbot.waitUntil(lambda: len(window.model.rows) == 5, timeout=10000)
    qtbot.waitUntil(lambda: window.start_btn.isEnabled(), timeout=10000)
    # újraolvasáskor a kézzel hozzáadott fájlok megmaradnak
    window.rescan()
    qtbot.waitUntil(lambda: len(window.model.rows) == 5 and window.start_btn.isEnabled(), timeout=10000)
