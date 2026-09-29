"""Egyetlen kép betöltése, előkészítése és kódolása WebP / AVIF formátumba."""

from __future__ import annotations

import io
import os
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from PIL import ExifTags, Image, ImageCms, ImageOps, ImageSequence, UnidentifiedImageError

from ..i18n import tr
from .formats import PIL_FORMATS, WEBP_MAX_DIMENSION, register_optional_plugins
from .models import Job, JobResult, SkipReason, Status, TargetResult
from .resize import ResizePlan, apply_resize, plan_resize, sharpen
from .scanner import TEMP_PREFIX
from .settings import ColorProfile, ConversionSettings, OutputFormat

# A mkstemp 0600-as jogosultsággal hoz létre fájlt; a kész kimenetnek viszont
# a szokásos (umask szerinti) jogosultság kell, különben pl. egy webszerver nem
# tudná olvasni. Az umask lekérdezése nem szálbiztos, ezért importáláskor tesszük.
_UMASK = os.umask(0)
os.umask(_UMASK)

ORIENTATION_TAG = ExifTags.Base.Orientation
GPS_IFD_TAG = ExifTags.Base.GPSInfo
_GRAY16_MODES = {"I", "I;16", "I;16L", "I;16B", "I;16N", "F"}


class ConversionCancelled(Exception):
    pass


@dataclass
class PreparedImage:
    """Betöltött, elforgatott, színkezelt és átméretezett képkocká(k)."""

    frames: list[Image.Image]
    durations: list[int] | None = None
    loop: int = 0
    icc_profile: bytes | None = None
    exif: bytes | None = None
    xmp: bytes | None = None
    original_dims: tuple[int, int] = (0, 0)
    warnings: list[str] = field(default_factory=list)

    @property
    def animated(self) -> bool:
        return len(self.frames) > 1

    @property
    def dims(self) -> tuple[int, int]:
        return self.frames[0].size

    def close(self) -> None:
        for f in self.frames:
            try:
                f.close()
            except Exception:
                pass


@dataclass
class EncodeResult:
    data: bytes
    quality: int | None
    note: str = ""


def _check_cancel(cancel: threading.Event | None) -> None:
    if cancel is not None and cancel.is_set():
        raise ConversionCancelled()


# --------------------------------------------------------------------------
# Színkezelés
# --------------------------------------------------------------------------


def _srgb_profile() -> ImageCms.ImageCmsProfile:
    return ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB"))


def _is_srgb(icc: bytes) -> bool:
    try:
        desc = ImageCms.getProfileDescription(ImageCms.ImageCmsProfile(io.BytesIO(icc)))
    except Exception:
        return False
    return "srgb" in (desc or "").lower()


def _icc_convert(img: Image.Image, icc: bytes, out_mode: str) -> Image.Image:
    return ImageCms.profileToProfile(
        img,
        ImageCms.ImageCmsProfile(io.BytesIO(icc)),
        _srgb_profile(),
        renderingIntent=ImageCms.Intent.RELATIVE_COLORIMETRIC,
        outputMode=out_mode,
        flags=ImageCms.Flags.BLACKPOINTCOMPENSATION,
    )


def _gray16_to_8bit(img: Image.Image) -> Image.Image:
    if img.mode == "F":
        _lo, hi = img.getextrema()
        scale = 255.0 if hi <= 1.0 else (255.0 / 65535.0 if hi > 255 else 1.0)
        return img.point(lambda v: v * scale).convert("L")
    img = img.convert("I")
    _lo, hi = img.getextrema()
    if hi > 255:
        img = img.point(lambda v: v * (1 / 257))
    return img.convert("L")


def normalize_mode(
    img: Image.Image, icc: bytes | None, policy: ColorProfile, warnings: list[str]
) -> tuple[Image.Image, bytes | None]:
    """A képet L / RGB / RGBA módra hozza és alkalmazza a színprofil-szabályt.

    Visszaadja a képet és a kimenetbe ágyazandó ICC profilt (vagy None)."""
    mode = img.mode
    if mode == "1":
        img = img.convert("L")
    elif mode in _GRAY16_MODES:
        img = _gray16_to_8bit(img)
    elif mode in ("P", "PA"):
        img = img.convert("RGBA" if img.has_transparency_data else "RGB")
    elif mode in ("LA", "La", "RGBa"):
        img = img.convert("RGBA")
    elif mode in ("RGBX", "YCbCr", "LAB", "HSV"):
        img = img.convert("RGB")
    elif mode == "L" and "transparency" in img.info:
        img = img.convert("RGBA")
    elif mode == "RGB" and "transparency" in img.info:
        img = img.convert("RGBA")

    if img.mode == "CMYK":
        # CMYK profil RGB kimenetbe nem ágyazható: mindig sRGB-re alakítunk.
        if icc:
            try:
                return _icc_convert(img, icc, "RGB"), None
            except Exception:
                warnings.append(tr("warn.icc_failed"))
        return img.convert("RGB"), None

    if img.mode not in ("L", "RGB", "RGBA"):
        img = img.convert("RGBA" if img.has_transparency_data else "RGB")

    if not icc or policy is ColorProfile.STRIP:
        return img, None
    if policy is ColorProfile.KEEP:
        return img, icc
    # sRGB: a böngészők címke nélkül is sRGB-nek tekintik a képet.
    if img.mode == "L" or _is_srgb(icc):
        return img, None
    try:
        return _icc_convert(img, icc, img.mode), None
    except Exception:
        warnings.append(tr("warn.icc_failed"))
        return img, icc


# --------------------------------------------------------------------------
# Betöltés és előkészítés
# --------------------------------------------------------------------------


def _oriented_size(size: tuple[int, int], orientation: int) -> tuple[int, int]:
    return (size[1], size[0]) if orientation in (5, 6, 7, 8) else size


def _maybe_draft(im: Image.Image, plan: ResizePlan | None, orientation: int) -> None:
    """JPEG-nél a dekóder eleve kisebb méretben (1/2, 1/4, 1/8) is tud
    olvasni – nagy kicsinyítésnél ez sokszoros gyorsulás. 2× tartalékot
    hagyunk, így a végső Lanczos-szűrés minősége nem romlik."""
    if plan is None or im.format not in ("JPEG", "MPO"):
        return
    w, h = im.size
    ow, oh = _oriented_size((w, h), orientation)
    if plan.crop is not None:
        l, t, r, b = plan.crop
        crop_w, crop_h = (r - l) * ow, (b - t) * oh
        need_w = ow * plan.size[0] / crop_w
        need_h = oh * plan.size[1] / crop_h
    else:
        need_w, need_h = plan.size
    need = (int(need_w * 2) + 1, int(need_h * 2) + 1)
    need = _oriented_size(need, orientation)  # vissza a nyers (forgatás előtti) térbe
    if need[0] < w and need[1] < h:
        im.draft(None, need)


def _extract_xmp(info: dict) -> bytes | None:
    xmp = info.get("xmp") or info.get("XML:com.adobe.xmp")
    if isinstance(xmp, str):
        xmp = xmp.encode("utf-8")
    return xmp or None


def _exif_bytes(img: Image.Image, settings: ConversionSettings, oriented: bool) -> bytes | None:
    meta = settings.metadata
    if not meta.keep_exif:
        return None
    exif = img.getexif()
    if not exif:
        return None
    if oriented:
        exif.pop(ORIENTATION_TAG, None)
    if meta.strip_gps:
        exif.pop(GPS_IFD_TAG, None)
    data = exif.tobytes()
    return data if len(data) > 8 else None


def _finish_frame(
    frame: Image.Image,
    icc: bytes | None,
    settings: ConversionSettings,
    plan: ResizePlan | None,
    warnings: list[str],
) -> tuple[Image.Image, bytes | None]:
    frame, out_icc = normalize_mode(frame, icc, settings.metadata.color_profile, warnings)
    resized = apply_resize(frame, plan, settings.resize.resample)
    if settings.resize.sharpen:
        resized = sharpen(resized, settings.resize.sharpen_amount)
    return resized, out_icc


def prepare_image(
    path: Path | str,
    settings: ConversionSettings,
    cancel: threading.Event | None = None,
    max_frames: int | None = None,
) -> PreparedImage:
    """Betölti és a beállítások szerint előkészíti a képet (még kódolás előtt)."""
    register_optional_plugins()
    meta = settings.metadata
    warnings: list[str] = []
    with Image.open(path) as im:
        n_frames = getattr(im, "n_frames", 1)
        # Az MPO (több képet tartalmazó JPEG – sok telefon és fényképezőgép így
        # ment előnézetet/mélységtérképet) nem animáció: csak a fő képet használjuk.
        animated = (
            settings.keep_animation
            and n_frames > 1
            and getattr(im, "is_animated", False)
            and im.format not in ("MPO", "TIFF")
        )
        icc = im.info.get("icc_profile")
        orientation = 1
        if meta.auto_orient and not animated:
            try:
                orientation = int(im.getexif().get(ORIENTATION_TAG, 1) or 1)
            except Exception:
                orientation = 1
        original_dims = _oriented_size(im.size, orientation)
        plan = plan_resize(*original_dims, settings.resize)

        if animated:
            loop = int(im.info.get("loop", 0) or 0)
            default_duration = int(im.info.get("duration", 100) or 100)
            frames: list[Image.Image] = []
            durations: list[int] = []
            out_icc = None
            for idx, raw in enumerate(ImageSequence.Iterator(im)):
                _check_cancel(cancel)
                if max_frames is not None and idx >= max_frames:
                    break
                durations.append(int(raw.info.get("duration", default_duration) or default_duration))
                frame = raw.convert("RGBA")
                frame, out_icc = _finish_frame(frame, icc, settings, plan, warnings)
                frames.append(frame)
            xmp = _extract_xmp(im.info) if meta.keep_xmp else None
            exif = _exif_bytes(im, settings, oriented=False)
            return PreparedImage(
                frames, durations, loop, out_icc, exif, xmp, original_dims, _dedupe(warnings)
            )

        _maybe_draft(im, plan, orientation)
        im.load()
        _check_cancel(cancel)
        frame = ImageOps.exif_transpose(im) if meta.auto_orient else im.copy()
        if frame is None:  # régebbi Pillow in_place viselkedés védelme
            frame = im.copy()
        xmp = _extract_xmp(frame.info) if meta.keep_xmp else None
        exif = _exif_bytes(frame, settings, oriented=meta.auto_orient)
        _check_cancel(cancel)
        result, out_icc = _finish_frame(frame, icc, settings, plan, warnings)
        if result is not frame:
            frame.close()
        return PreparedImage([result], None, 0, out_icc, exif, xmp, original_dims, _dedupe(warnings))


def _dedupe(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))


# --------------------------------------------------------------------------
# Kódolás
# --------------------------------------------------------------------------


def encode(
    prepared: PreparedImage,
    fmt: OutputFormat,
    settings: ConversionSettings,
    quality: int | None = None,
    avif_threads: int | None = None,
) -> bytes:
    """A kép kódolása memóriába a megadott formátumban."""
    frames = prepared.frames
    base = frames[0]
    params: dict = {}
    if prepared.icc_profile:
        params["icc_profile"] = prepared.icc_profile
    if prepared.exif:
        params["exif"] = prepared.exif
    if prepared.xmp:
        params["xmp"] = prepared.xmp

    if fmt is OutputFormat.WEBP:
        o = settings.webp
        if max(base.size) > WEBP_MAX_DIMENSION:
            raise ValueError(tr("err.webp_too_large", max=WEBP_MAX_DIMENSION, w=base.size[0], h=base.size[1]))
        q = o.quality if quality is None else quality
        params.update(
            quality=int(q),
            lossless=o.lossless,
            method=o.method,
            alpha_quality=o.alpha_quality,
            exact=o.exact,
        )
        if prepared.animated:
            params.update(
                save_all=True,
                append_images=frames[1:],
                duration=prepared.durations,
                loop=prepared.loop,
                minimize_size=o.method >= 5,
                allow_mixed=not o.lossless,
            )
    else:
        o = settings.avif
        q = o.quality if quality is None else quality
        subsampling = o.subsampling
        if o.lossless:
            q, subsampling = 100, "4:4:4"
        if all(f.mode == "L" for f in frames):
            subsampling = "4:0:0"
        params.update(quality=int(q), speed=o.speed, subsampling=subsampling)
        if avif_threads:
            params["max_threads"] = int(avif_threads)
        if prepared.animated:
            params.update(save_all=True, append_images=frames[1:], duration=prepared.durations)

    buf = io.BytesIO()
    base.save(buf, PIL_FORMATS[fmt], **params)
    return buf.getvalue()


def encode_for_settings(
    prepared: PreparedImage,
    fmt: OutputFormat,
    settings: ConversionSettings,
    avif_threads: int | None = None,
    cancel: threading.Event | None = None,
) -> EncodeResult:
    """Kódolás a beállított minőséggel, vagy – célméret módban – bináris
    kereséssel a legjobb minőségre, ami még belefér a méretkorlátba."""
    lossless = settings.is_lossless(fmt)
    max_q = settings.quality_for(fmt)
    if not settings.target_size_enabled or lossless:
        data = encode(prepared, fmt, settings, None, avif_threads)
        note = tr("note.lossless_no_target") if settings.target_size_enabled and lossless else ""
        return EncodeResult(data, None if lossless else max_q, note)

    target = settings.target_size_kb * 1024
    min_q = min(settings.target_min_quality, max_q)
    data = encode(prepared, fmt, settings, max_q, avif_threads)
    if len(data) <= target:
        return EncodeResult(data, max_q)

    best: tuple[bytes, int] | None = None
    smallest: tuple[bytes, int] = (data, max_q)
    lo, hi = min_q, max_q - 1
    while lo <= hi:
        _check_cancel(cancel)
        mid = (lo + hi) // 2
        candidate = encode(prepared, fmt, settings, mid, avif_threads)
        if len(candidate) < len(smallest[0]):
            smallest = (candidate, mid)
        if len(candidate) <= target:
            best = (candidate, mid)
            lo = mid + 1
        else:
            hi = mid - 1
    if best is not None:
        return EncodeResult(best[0], best[1], tr("note.target_quality", q=best[1]))
    return EncodeResult(
        smallest[0], smallest[1], tr("note.target_not_reached", kb=settings.target_size_kb)
    )


# --------------------------------------------------------------------------
# Fájlírás és egy feladat teljes feldolgozása
# --------------------------------------------------------------------------


def write_atomic(dest: Path, data: bytes, source_stat: os.stat_result | None = None) -> None:
    """Ideiglenes fájlba ír, majd átnevezi – megszakításkor sem marad félkész fájl."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=TEMP_PREFIX, suffix=".tmp", dir=dest.parent)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.chmod(tmp, 0o666 & ~_UMASK)
        os.replace(tmp, dest)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    if source_stat is not None:
        try:
            os.utime(dest, ns=(source_stat.st_atime_ns, source_stat.st_mtime_ns))
        except OSError:
            pass


def convert_job(
    job: Job,
    settings: ConversionSettings,
    cancel: threading.Event | None = None,
    avif_threads: int | None = None,
) -> JobResult:
    started = time.perf_counter()
    result = JobResult(job.index, job.source, job.source_size)
    active = []
    for t in job.targets:
        if t.skip is not None:
            result.targets.append(
                TargetResult(t.fmt, t.dest, Status.SKIPPED, skip=t.skip, note=tr(f"skip.{t.skip.value}"))
            )
        else:
            active.append(t)
    if not active:
        result.finalize_status()
        result.elapsed = time.perf_counter() - started
        return result

    prepared: PreparedImage | None = None
    try:
        _check_cancel(cancel)
        src_stat = job.source.stat()
        prepared = prepare_image(job.source, settings, cancel)
        result.original_dims = prepared.original_dims
        result.output_dims = prepared.dims
        result.frames = len(prepared.frames)
        result.warnings.extend(prepared.warnings)
        for t in active:
            _check_cancel(cancel)
            try:
                enc = encode_for_settings(prepared, t.fmt, settings, avif_threads, cancel)
            except ConversionCancelled:
                raise
            except Exception as exc:  # egy formátum hibája ne vigye el a másikat
                result.targets.append(TargetResult(t.fmt, t.dest, Status.FAILED, note=_error_text(exc)))
                continue
            _check_cancel(cancel)
            if settings.skip_if_larger and len(enc.data) >= job.source_size:
                result.targets.append(
                    TargetResult(
                        t.fmt, t.dest, Status.SKIPPED, len(enc.data), enc.quality,
                        SkipReason.LARGER, tr("skip.larger"),
                    )
                )
                continue
            write_atomic(
                t.dest, enc.data, src_stat if settings.metadata.preserve_timestamps else None
            )
            note = enc.note
            if t.renamed:
                note = "; ".join(filter(None, [note, tr("note.renamed", name=t.dest.name)]))
            result.targets.append(
                TargetResult(t.fmt, t.dest, Status.DONE, len(enc.data), enc.quality, note=note)
            )
    except ConversionCancelled:
        done = {r.fmt for r in result.targets}
        for t in active:
            if t.fmt not in done:
                result.targets.append(TargetResult(t.fmt, t.dest, Status.CANCELLED))
    except UnidentifiedImageError:
        result.error = tr("err.unidentified")
    except Exception as exc:
        result.error = _error_text(exc)
    finally:
        if prepared is not None:
            prepared.close()
    if result.error:
        done = {r.fmt for r in result.targets}
        for t in active:
            if t.fmt not in done:
                result.targets.append(TargetResult(t.fmt, t.dest, Status.FAILED, note=result.error))
    result.finalize_status()
    result.elapsed = time.perf_counter() - started
    return result


def _error_text(exc: BaseException) -> str:
    if isinstance(exc, Image.DecompressionBombError):
        return tr("err.too_many_pixels")
    if isinstance(exc, MemoryError):
        return tr("err.memory")
    if isinstance(exc, PermissionError):
        return tr("err.permission", path=getattr(exc, "filename", "") or "")
    if isinstance(exc, FileNotFoundError):
        return tr("err.not_found", path=getattr(exc, "filename", "") or "")
    msg = str(exc).strip()
    return msg or type(exc).__name__


def convert_preview(
    path: Path | str,
    settings: ConversionSettings,
    fmt: OutputFormat,
    quality: int | None = None,
    prepared: PreparedImage | None = None,
) -> tuple[bytes, PreparedImage]:
    """Memóriában kódol (előnézethez / becsléshez); az előkészített kép
    újrahasznosítható, ha csak a minőség változik."""
    if prepared is None:
        prepared = prepare_image(path, settings, max_frames=1)
    data = encode(prepared, fmt, settings, quality)
    return data, prepared
