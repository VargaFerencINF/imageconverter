"""Beépített beállítás-sablonok (presetek)."""

from __future__ import annotations

from dataclasses import dataclass

from ..i18n import tr
from .settings import (
    AvifOptions,
    ColorProfile,
    ConversionSettings,
    MetadataOptions,
    NamingOptions,
    OutputFormat,
    ResizeMode,
    ResizeOptions,
    WebPOptions,
)


@dataclass
class Preset:
    key: str
    settings: ConversionSettings
    builtin: bool = True
    custom_name: str = ""

    @property
    def name(self) -> str:
        return tr(f"preset.{self.key}") if self.builtin else self.custom_name

    @property
    def description(self) -> str:
        return tr(f"preset.{self.key}.desc") if self.builtin else ""


def _web_meta() -> MetadataOptions:
    return MetadataOptions(keep_exif=False, keep_xmp=False, color_profile=ColorProfile.SRGB)


def builtin_presets() -> list[Preset]:
    both = [OutputFormat.WEBP, OutputFormat.AVIF]
    return [
        Preset(
            "balanced",
            ConversionSettings(
                formats=[OutputFormat.WEBP],
                webp=WebPOptions(quality=80, method=4),
                avif=AvifOptions(quality=60, speed=6),
            ),
        ),
        Preset(
            "high_quality",
            ConversionSettings(
                formats=[OutputFormat.WEBP],
                webp=WebPOptions(quality=92, method=6),
                avif=AvifOptions(quality=80, speed=4, subsampling="4:4:4"),
                metadata=MetadataOptions(keep_exif=True, strip_gps=True, color_profile=ColorProfile.SRGB),
            ),
        ),
        Preset(
            "max_compression",
            ConversionSettings(
                formats=[OutputFormat.AVIF],
                webp=WebPOptions(quality=60, method=6),
                avif=AvifOptions(quality=45, speed=4),
                metadata=_web_meta(),
            ),
        ),
        Preset(
            "web_fullhd",
            ConversionSettings(
                formats=both,
                webp=WebPOptions(quality=80, method=5),
                avif=AvifOptions(quality=60, speed=6),
                resize=ResizeOptions(mode=ResizeMode.LONG_EDGE, long_edge=1920),
                metadata=_web_meta(),
                naming=NamingOptions(web_safe=True),
            ),
        ),
        Preset(
            "web_blog",
            ConversionSettings(
                formats=both,
                webp=WebPOptions(quality=78, method=5),
                avif=AvifOptions(quality=58, speed=6),
                resize=ResizeOptions(mode=ResizeMode.WIDTH, width=1200),
                metadata=_web_meta(),
                naming=NamingOptions(web_safe=True),
            ),
        ),
        Preset(
            "webshop",
            ConversionSettings(
                formats=[OutputFormat.WEBP],
                webp=WebPOptions(quality=82, method=5),
                avif=AvifOptions(quality=62, speed=6),
                resize=ResizeOptions(mode=ResizeMode.FIT, width=1000, height=1000, sharpen=True, sharpen_amount=40),
                metadata=_web_meta(),
                naming=NamingOptions(web_safe=True),
            ),
        ),
        Preset(
            "thumbnail",
            ConversionSettings(
                formats=[OutputFormat.WEBP],
                webp=WebPOptions(quality=75, method=6),
                avif=AvifOptions(quality=55, speed=6),
                resize=ResizeOptions(mode=ResizeMode.FILL, width=400, height=400, sharpen=True, sharpen_amount=60),
                metadata=_web_meta(),
                naming=NamingOptions(suffix="-thumb", web_safe=True),
            ),
        ),
        Preset(
            "max_100kb",
            ConversionSettings(
                formats=[OutputFormat.WEBP],
                webp=WebPOptions(quality=85, method=6),
                avif=AvifOptions(quality=70, speed=6),
                resize=ResizeOptions(mode=ResizeMode.LONG_EDGE, long_edge=1920),
                metadata=_web_meta(),
                target_size_enabled=True,
                target_size_kb=100,
                target_min_quality=25,
            ),
        ),
        Preset(
            "lossless",
            ConversionSettings(
                formats=[OutputFormat.WEBP],
                webp=WebPOptions(quality=90, lossless=True, method=6, exact=True),
                avif=AvifOptions(quality=100, lossless=True, speed=4, subsampling="4:4:4"),
                metadata=MetadataOptions(keep_exif=True, keep_xmp=True, strip_gps=False, color_profile=ColorProfile.KEEP),
            ),
        ),
    ]


def find_builtin(key: str) -> Preset | None:
    for p in builtin_presets():
        if p.key == key:
            return p
    return None
