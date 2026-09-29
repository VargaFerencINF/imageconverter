# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec – egyetlen elemzésből három kimenet:

* dist/WebKepKonverter/            – mappás változat (a telepítő ezt csomagolja; gyors indulás)
* dist/WebKepKonverter-Portable.exe – egyetlen hordozható exe
* dist/webkep-cli.exe               – parancssori változat (Qt nélkül, kicsi)

Futtatás a projekt gyökeréből:  pyinstaller --noconfirm packaging/webkep.spec
"""

import os
import sys
from pathlib import Path

ROOT = Path(SPECPATH).resolve().parent
sys.path.insert(0, str(ROOT))

from webkep import APP_NAME, REPO_URL, __version__  # noqa: E402

ICON = str(ROOT / "assets" / "icon.ico")
TARGETS = set(os.environ.get("WEBKEP_TARGETS", "onedir,onefile,cli").split(","))


def version_resource(internal_name: str, description: str, filename: str):
    if sys.platform != "win32":  # a verzió-erőforrás csak Windows exe-be kerül
        return None
    from PyInstaller.utils.win32.versioninfo import (
        FixedFileInfo,
        StringFileInfo,
        StringStruct,
        StringTable,
        VarFileInfo,
        VarStruct,
        VSVersionInfo,
    )

    nums = tuple(int(p) for p in (__version__.split(".") + ["0", "0", "0"])[:4])
    return VSVersionInfo(
        ffi=FixedFileInfo(filevers=nums, prodvers=nums, mask=0x3F, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0),
        kids=[
            StringFileInfo(
                [
                    StringTable(
                        "040E04B0",  # magyar, Unicode
                        [
                            StringStruct("CompanyName", "WebKep"),
                            StringStruct("FileDescription", description),
                            StringStruct("FileVersion", __version__),
                            StringStruct("InternalName", internal_name),
                            StringStruct("LegalCopyright", REPO_URL),
                            StringStruct("OriginalFilename", filename),
                            StringStruct("ProductName", APP_NAME),
                            StringStruct("ProductVersion", __version__),
                        ],
                    )
                ]
            ),
            VarFileInfo([VarStruct("Translation", [0x040E, 1200])]),
        ],
    )


COMMON_EXCLUDES = [
    "tkinter",
    "_tkinter",
    "unittest",
    "pydoc",
    "doctest",
    "numpy",
    "pytest",
    "PyInstaller",
]
# A felület csak a QtCore / QtGui / QtWidgets / QtSvg modulokat használja.
UNUSED_QT = [
    "PySide6.QtNetwork",
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.QtQuickWidgets",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebChannel",
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
    "PySide6.Qt3DCore",
    "PySide6.QtCharts",
    "PySide6.QtDataVisualization",
    "PySide6.QtPdf",
    "PySide6.QtPdfWidgets",
    "PySide6.QtSql",
    "PySide6.QtTest",
    "PySide6.QtBluetooth",
    "PySide6.QtPositioning",
    "PySide6.QtSensors",
    "PySide6.QtSerialPort",
    "PySide6.QtDesigner",
    "PySide6.QtHelp",
    "PySide6.QtOpenGL",
    "PySide6.QtOpenGLWidgets",
    "PySide6.QtXml",
]
HIDDEN = ["PIL.AvifImagePlugin", "PIL.WebPImagePlugin", "pi_heif"]

# A Qt-hookok néhány nagy, itt felesleges függőséget is behúznak
# (PDF/QML/Quick pluginek, szoftveres OpenGL, virtuális billentyűzet…).
DROP_PATTERNS = (
    "qt6pdf",
    "qpdf",
    "qt6qml",
    "qt6quick",
    "virtualkeyboard",
    "platforminputcontexts",
    "qt6network",
    "plugins/tls",
    "plugins/networkinformation",
    "opengl32sw",
    "d3dcompiler",
    "platformthemes/libqgtk3",
    "egldeviceintegrations",
    "wayland",
)
KEEP_TRANSLATIONS = ("qtbase_hu", "qtbase_en")


def _keep(entry) -> bool:
    name = str(entry[0]).replace("\\", "/").lower()
    if "/translations/" in name and name.endswith(".qm"):
        return any(k in name for k in KEEP_TRANSLATIONS)
    return not any(p in name for p in DROP_PATTERNS)


def slim(analysis) -> None:
    analysis.binaries = [b for b in analysis.binaries if _keep(b)]
    analysis.datas = [d for d in analysis.datas if _keep(d)]
DATAS = [(str(ROOT / "assets" / "icon.png"), "assets"), (str(ROOT / "assets" / "icon.ico"), "assets")]
for extra in ("README.md", "THIRD_PARTY_NOTICES.md"):
    if (ROOT / extra).exists():
        DATAS.append((str(ROOT / extra), "."))

if TARGETS & {"onedir", "onefile"}:
    gui = Analysis(
        [str(ROOT / "packaging" / "run_gui.py")],
        pathex=[str(ROOT)],
        datas=DATAS,
        hiddenimports=HIDDEN,
        excludes=COMMON_EXCLUDES + UNUSED_QT,
        noarchive=False,
        optimize=1,
    )
    slim(gui)
    gui_pyz = PYZ(gui.pure)

    if "onedir" in TARGETS:
        gui_exe = EXE(
            gui_pyz,
            gui.scripts,
            [],
            exclude_binaries=True,
            name="WebKepKonverter",
            icon=ICON,
            version=version_resource("WebKepKonverter", APP_NAME, "WebKepKonverter.exe"),
            console=False,
            upx=False,
        )
        COLLECT(gui_exe, gui.binaries, gui.datas, name="WebKepKonverter", upx=False)

    if "onefile" in TARGETS:
        EXE(
            gui_pyz,
            gui.scripts,
            gui.binaries,
            gui.datas,
            [],
            name="WebKepKonverter-Portable",
            icon=ICON,
            version=version_resource("WebKepKonverter-Portable", f"{APP_NAME} (hordozható)", "WebKepKonverter-Portable.exe"),
            console=False,
            upx=False,
            runtime_tmpdir=None,
        )

if "cli" in TARGETS:
    cli = Analysis(
        [str(ROOT / "packaging" / "run_cli.py")],
        pathex=[str(ROOT)],
        datas=[],
        hiddenimports=HIDDEN,
        excludes=COMMON_EXCLUDES + ["PySide6", "shiboken6"],
        optimize=1,
    )
    EXE(
        PYZ(cli.pure),
        cli.scripts,
        cli.binaries,
        cli.datas,
        [],
        name="webkep-cli",
        icon=ICON,
        version=version_resource("webkep-cli", f"{APP_NAME} – parancssor", "webkep-cli.exe"),
        console=True,
        upx=False,
    )
