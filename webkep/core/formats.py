"""Támogatott be- és kimeneti formátumok, opcionális pluginok."""

from __future__ import annotations

import platform
import sys
import warnings

import PIL
from PIL import Image, features

from .settings import INPUT_GROUP_KEYS, OutputFormat

# Nagy panorámák / nyomdai képek is menjenek át, de a valódi "bomba" ne.
Image.MAX_IMAGE_PIXELS = 400_000_000
warnings.simplefilter("ignore", Image.DecompressionBombWarning)

INPUT_GROUPS: dict[str, tuple[str, ...]] = {
    "jpeg": (".jpg", ".jpeg", ".jpe", ".jfif"),
    "png": (".png",),
    "bmp": (".bmp", ".dib"),
    "gif": (".gif",),
    "tiff": (".tif", ".tiff"),
    "webp": (".webp",),
    "avif": (".avif",),
    "heic": (".heic", ".heif"),
    "other": (".ico", ".tga", ".ppm", ".pgm", ".pbm", ".pnm", ".jp2", ".j2k", ".psd"),
}
assert tuple(INPUT_GROUPS) == INPUT_GROUP_KEYS

OUTPUT_EXTENSIONS = {OutputFormat.WEBP: ".webp", OutputFormat.AVIF: ".avif"}
PIL_FORMATS = {OutputFormat.WEBP: "WEBP", OutputFormat.AVIF: "AVIF"}

WEBP_MAX_DIMENSION = 16383

_heif_state: bool | None = None


def register_optional_plugins() -> None:
    """HEIC/HEIF olvasás engedélyezése.

    Elsősorban a csak dekódoló, LGPL licencű ``pi-heif`` csomagot használjuk;
    a ``pillow-heif`` (amely GPL-es x265 kódolót is tartalmaz) csak tartalék."""
    global _heif_state
    if _heif_state is not None:
        return
    _heif_state = False
    for module in ("pi_heif", "pillow_heif"):
        try:
            mod = __import__(module)
            mod.register_heif_opener()
            _heif_state = True
            return
        except Exception:  # pragma: no cover - környezetfüggő
            continue


def heif_available() -> bool:
    register_optional_plugins()
    return bool(_heif_state)


def _check_feature(name: str) -> bool:
    try:
        return bool(features.check(name))
    except Exception:
        return False


def output_available(fmt: OutputFormat) -> bool:
    return _check_feature("webp" if fmt is OutputFormat.WEBP else "avif")


def extensions_for_groups(groups: list[str] | tuple[str, ...]) -> set[str]:
    exts: set[str] = set()
    for g in groups:
        if g == "heic" and not heif_available():
            continue
        exts.update(INPUT_GROUPS.get(g, ()))
    return exts


def all_input_extensions() -> set[str]:
    return extensions_for_groups(INPUT_GROUP_KEYS)


def library_versions() -> dict[str, str]:
    """A névjegy ablakhoz: a használt könyvtárak és kodekek verziói."""
    info = {
        "Python": platform.python_version(),
        "Pillow": PIL.__version__,
        "libwebp": features.version("webp") or "-",
        "libavif": (features.version("avif") or "-") if _check_feature("avif") else "-",
    }
    try:
        from PIL import _avif  # type: ignore[attr-defined]

        info["AVIF codecs"] = _avif.codec_versions()
    except Exception:
        pass
    for module, label in (("pi_heif", "pi-heif (HEIC)"), ("pillow_heif", "pillow-heif (HEIC)")):
        try:
            info[label] = __import__(module).__version__
            break
        except Exception:
            continue
    else:
        info["HEIC"] = "-"
    info["Platform"] = f"{platform.system()} {platform.release()} ({sys.platform})"
    return info
