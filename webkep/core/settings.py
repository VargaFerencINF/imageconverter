"""Konverziós beállítások adatszerkezetei, JSON-szerializálással és validálással."""

from __future__ import annotations

import dataclasses
import typing
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, TypeVar

T = TypeVar("T")


class OutputFormat(str, Enum):
    WEBP = "webp"
    AVIF = "avif"


class ResizeMode(str, Enum):
    NONE = "none"
    PERCENT = "percent"
    WIDTH = "width"
    HEIGHT = "height"
    LONG_EDGE = "long_edge"
    FIT = "fit"
    FILL = "fill"


class Resample(str, Enum):
    LANCZOS = "lanczos"
    BICUBIC = "bicubic"
    BILINEAR = "bilinear"
    NEAREST = "nearest"


class ColorProfile(str, Enum):
    SRGB = "srgb"
    KEEP = "keep"
    STRIP = "strip"


class ConflictPolicy(str, Enum):
    OVERWRITE = "overwrite"
    SKIP = "skip"
    RENAME = "rename"
    UPDATE = "update"


AVIF_SUBSAMPLINGS = ("4:2:0", "4:2:2", "4:4:4")


def _clamp(value: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, int(value)))


@dataclass
class WebPOptions:
    quality: int = 80
    lossless: bool = False
    method: int = 4
    alpha_quality: int = 100
    exact: bool = False

    def validate(self) -> None:
        self.quality = _clamp(self.quality, 0, 100)
        self.method = _clamp(self.method, 0, 6)
        self.alpha_quality = _clamp(self.alpha_quality, 0, 100)


@dataclass
class AvifOptions:
    quality: int = 60
    lossless: bool = False
    speed: int = 6
    subsampling: str = "4:2:0"

    def validate(self) -> None:
        self.quality = _clamp(self.quality, 0, 100)
        self.speed = _clamp(self.speed, 0, 10)
        if self.subsampling not in AVIF_SUBSAMPLINGS:
            self.subsampling = "4:2:0"


@dataclass
class ResizeOptions:
    mode: ResizeMode = ResizeMode.NONE
    percent: int = 50
    width: int = 1920
    height: int = 1080
    long_edge: int = 1920
    allow_upscale: bool = False
    resample: Resample = Resample.LANCZOS
    sharpen: bool = False
    sharpen_amount: int = 60

    def validate(self) -> None:
        self.percent = _clamp(self.percent, 1, 1000)
        self.width = _clamp(self.width, 1, 65535)
        self.height = _clamp(self.height, 1, 65535)
        self.long_edge = _clamp(self.long_edge, 1, 65535)
        self.sharpen_amount = _clamp(self.sharpen_amount, 1, 300)


@dataclass
class MetadataOptions:
    auto_orient: bool = True
    keep_exif: bool = False
    strip_gps: bool = True
    keep_xmp: bool = False
    color_profile: ColorProfile = ColorProfile.SRGB
    preserve_timestamps: bool = True


@dataclass
class NamingOptions:
    prefix: str = ""
    suffix: str = ""
    web_safe: bool = False
    lowercase: bool = False
    conflict: ConflictPolicy = ConflictPolicy.OVERWRITE


@dataclass
class ConversionSettings:
    """Minden, ami azt határozza meg, *mi* készüljön egy forrásképből."""

    formats: list[OutputFormat] = field(default_factory=lambda: [OutputFormat.WEBP])
    webp: WebPOptions = field(default_factory=WebPOptions)
    avif: AvifOptions = field(default_factory=AvifOptions)
    resize: ResizeOptions = field(default_factory=ResizeOptions)
    metadata: MetadataOptions = field(default_factory=MetadataOptions)
    naming: NamingOptions = field(default_factory=NamingOptions)
    keep_animation: bool = True
    target_size_enabled: bool = False
    target_size_kb: int = 200
    target_min_quality: int = 30
    skip_if_larger: bool = False

    def validate(self) -> "ConversionSettings":
        seen: list[OutputFormat] = []
        for fmt in self.formats:
            if fmt not in seen:
                seen.append(fmt)
        self.formats = seen
        self.webp.validate()
        self.avif.validate()
        self.resize.validate()
        self.target_size_kb = _clamp(self.target_size_kb, 1, 1_000_000)
        self.target_min_quality = _clamp(self.target_min_quality, 0, 100)
        return self

    def quality_for(self, fmt: OutputFormat) -> int:
        return self.webp.quality if fmt is OutputFormat.WEBP else self.avif.quality

    def is_lossless(self, fmt: OutputFormat) -> bool:
        return self.webp.lossless if fmt is OutputFormat.WEBP else self.avif.lossless

    def to_dict(self) -> dict[str, Any]:
        return to_dict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "ConversionSettings":
        return from_dict(cls, data or {}).validate()

    def copy(self) -> "ConversionSettings":
        return ConversionSettings.from_dict(self.to_dict())


INPUT_GROUP_KEYS = ("jpeg", "png", "bmp", "gif", "tiff", "webp", "avif", "heic", "other")
DEFAULT_INPUT_GROUPS = ("jpeg", "png", "bmp", "gif", "tiff", "heic", "other")


@dataclass
class SourceOptions:
    """Honnan olvasunk és hova kerülnek a kimeneti fájlok."""

    recursive: bool = True
    groups: list[str] = field(default_factory=lambda: list(DEFAULT_INPUT_GROUPS))
    keep_structure: bool = True
    beside_source: bool = False

    def validate(self) -> "SourceOptions":
        self.groups = [g for g in INPUT_GROUP_KEYS if g in set(self.groups)]
        return self


# --------------------------------------------------------------------------
# Általános (de)szerializálás dataclass-okhoz
# --------------------------------------------------------------------------


def to_dict(obj: Any) -> Any:
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: to_dict(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, (list, tuple)):
        return [to_dict(v) for v in obj]
    if isinstance(obj, dict):
        return {str(k): to_dict(v) for k, v in obj.items()}
    return obj


def _coerce(tp: Any, value: Any) -> Any:
    """Érték átalakítása a megadott típusra; hibánál kivételt dob."""
    if dataclasses.is_dataclass(tp):
        if not isinstance(value, dict):
            raise TypeError("dict expected")
        return from_dict(tp, value)
    if isinstance(tp, type) and issubclass(tp, Enum):
        return tp(value)
    if tp is bool:
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on")
        return bool(value)
    if tp is int:
        if isinstance(value, bool):
            return int(value)
        return int(float(value))
    if tp is float:
        return float(value)
    if tp is str:
        if value is None:
            raise TypeError("str expected")
        return str(value)
    origin = typing.get_origin(tp)
    args = typing.get_args(tp)
    if origin in (list, tuple):
        if not isinstance(value, (list, tuple)):
            raise TypeError("list expected")
        return [_coerce(args[0], v) for v in value] if args else list(value)
    if origin is dict:
        if not isinstance(value, dict):
            raise TypeError("dict expected")
        return dict(value)
    return value


def from_dict(cls: type[T], data: dict[str, Any]) -> T:
    """Dataclass létrehozása dict-ből; ismeretlen kulcsokat és hibás értékeket
    figyelmen kívül hagy (az alapértelmezés marad), így a régi/sérült
    beállításfájlok sem okoznak hibát."""
    hints = typing.get_type_hints(cls)
    obj = cls()
    for f in dataclasses.fields(cls):
        if f.name not in data:
            continue
        try:
            setattr(obj, f.name, _coerce(hints[f.name], data[f.name]))
        except (TypeError, ValueError, KeyError):
            pass
    return obj
