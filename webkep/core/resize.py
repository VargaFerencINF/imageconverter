"""Átméretezési logika: célméret számítása és alkalmazása."""

from __future__ import annotations

from dataclasses import dataclass

from PIL import Image, ImageFilter

from .settings import Resample, ResizeMode, ResizeOptions

RESAMPLE_FILTERS = {
    Resample.LANCZOS: Image.Resampling.LANCZOS,
    Resample.BICUBIC: Image.Resampling.BICUBIC,
    Resample.BILINEAR: Image.Resampling.BILINEAR,
    Resample.NEAREST: Image.Resampling.NEAREST,
}


@dataclass(frozen=True)
class ResizePlan:
    """A kimeneti méret és (kitöltő módban) a kivágás, a forráskép
    méretéhez viszonyított 0..1 arányokban – így JPEG draft-dekódolás után
    is ugyanazt a képrészt jelöli."""

    size: tuple[int, int]
    crop: tuple[float, float, float, float] | None = None


def plan_resize(width: int, height: int, opts: ResizeOptions) -> ResizePlan | None:
    """Kiszámolja a kimeneti méretet; ``None``, ha nem kell átméretezni."""
    if width <= 0 or height <= 0:
        return None
    mode = opts.mode
    if mode is ResizeMode.NONE:
        return None
    if mode is ResizeMode.FILL:
        return _plan_fill(width, height, opts)

    if mode is ResizeMode.PERCENT:
        scale = opts.percent / 100.0
    elif mode is ResizeMode.WIDTH:
        scale = opts.width / width
    elif mode is ResizeMode.HEIGHT:
        scale = opts.height / height
    elif mode is ResizeMode.LONG_EDGE:
        scale = opts.long_edge / max(width, height)
    elif mode is ResizeMode.FIT:
        scale = min(opts.width / width, opts.height / height)
    else:  # pragma: no cover - minden ág le van fedve
        return None

    if scale > 1 and not opts.allow_upscale:
        return None
    new_w = max(1, round(width * scale))
    new_h = max(1, round(height * scale))
    # Pontos értékek, ahol a felhasználó konkrét pixelt kért.
    if mode is ResizeMode.WIDTH:
        new_w = opts.width
    elif mode is ResizeMode.HEIGHT:
        new_h = opts.height
    if (new_w, new_h) == (width, height):
        return None
    return ResizePlan((new_w, new_h))


def _plan_fill(width: int, height: int, opts: ResizeOptions) -> ResizePlan | None:
    target_w, target_h = opts.width, opts.height
    ratio = target_w / target_h
    if width / height > ratio:  # túl széles: oldalakból vágunk
        crop_w, crop_h = height * ratio, float(height)
    else:  # túl magas: alulról/felülről vágunk
        crop_w, crop_h = float(width), width / ratio
    left = (width - crop_w) / 2
    top = (height - crop_h) / 2
    crop = (left / width, top / height, (left + crop_w) / width, (top + crop_h) / height)

    if crop_w >= target_w or opts.allow_upscale:
        size = (target_w, target_h)
    else:
        # Nagyítás nélkül: csak a képarányra vágunk, eredeti felbontásban.
        size = (max(1, round(crop_w)), max(1, round(crop_h)))
    full_crop = crop == (0.0, 0.0, 1.0, 1.0)
    if full_crop and size == (width, height):
        return None
    return ResizePlan(size, None if full_crop else crop)


def apply_resize(img: Image.Image, plan: ResizePlan | None, resample: Resample) -> Image.Image:
    if plan is None:
        return img
    w, h = img.size
    box = None
    if plan.crop is not None:
        l, t, r, b = plan.crop
        box = (l * w, t * h, r * w, b * h)
    if box is None and plan.size == img.size:
        return img
    filt = RESAMPLE_FILTERS[resample]
    # reducing_gap: nagy kicsinyítésnél sokkal gyorsabb, szemmel láthatatlan különbséggel
    gap = 3.0 if filt != Image.Resampling.NEAREST else None
    return img.resize(plan.size, filt, box=box, reducing_gap=gap)


def sharpen(img: Image.Image, amount: int) -> Image.Image:
    """Enyhe élesítés (unsharp mask) – az alfa csatornát nem érinti."""
    filt = ImageFilter.UnsharpMask(radius=1.0, percent=int(amount), threshold=2)
    if img.mode == "RGBA":
        rgb = img.convert("RGB").filter(filt)
        rgb.putalpha(img.getchannel("A"))
        return rgb
    if img.mode in ("RGB", "L"):
        return img.filter(filt)
    return img
