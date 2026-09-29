"""A grafikus alkalmazás belépési pontja."""

from __future__ import annotations

import os
import sys


def _set_windows_app_id() -> None:
    """Saját tálcaikon Windows alatt (ne a python.exe ikonja jelenjen meg)."""
    if os.name != "nt":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("WebKep.Konverter")  # type: ignore[attr-defined]
    except Exception:
        pass


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    _set_windows_app_id()

    from PySide6.QtCore import QLibraryInfo, Qt, QTranslator
    from PySide6.QtWidgets import QApplication, QStyleFactory

    from .. import APP_ID, APP_NAME, ORG_NAME, __version__
    from ..core.config import load_state
    from ..core.formats import register_optional_plugins
    from ..i18n import set_language

    state = load_state()
    set_language(state.language)
    register_optional_plugins()

    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setOrganizationName(ORG_NAME)
    app.setApplicationVersion(__version__)
    app.setDesktopFileName(APP_ID)
    app.setStyle(QStyleFactory.create("Fusion"))

    # A Qt beépített szövegei (Igen/Nem gombok, fájlpárbeszéd) a választott nyelven.
    translator = QTranslator(app)
    qt_lang = "hu" if state.language == "hu" else "en"
    if translator.load(f"qtbase_{qt_lang}", QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)):
        app.installTranslator(translator)

    from . import theme
    from .main_window import MainWindow

    theme.apply_theme(app, state.theme)
    app.setWindowIcon(theme.app_icon())

    window = MainWindow(state)
    window.show()

    # Mappa megadható parancssori argumentumként is (pl. "Megnyitás ezzel" / húzás az exe-re).
    paths = [a for a in argv[1:] if not a.startswith("-")]
    if paths and os.path.isdir(paths[0]):
        window.input_picker.setPath(paths[0])

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
