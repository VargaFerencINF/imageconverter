import io
import os
from pathlib import Path

import pytest
from PIL import ExifTags, Image, ImageCms

from webkep.core.converter import convert_preview, encode, normalize_mode, prepare_image
from webkep.core.models import Job, Status, Target
from webkep.core.converter import convert_job
from webkep.core.settings import (
    ColorProfile,
    ConversionSettings,
    MetadataOptions,
    OutputFormat,
    ResizeMode,
    ResizeOptions,
    WebPOptions,
)

from .conftest import photo


def run(src: Path, out: Path, settings: ConversionSettings):
    targets = [Target(fmt, out / (src.stem + "." + fmt.value)) for fmt in settings.formats]
    return convert_job(Job(0, src, src.stat().st_size, targets), settings.validate())


@pytest.mark.parametrize("fmt", [OutputFormat.WEBP, OutputFormat.AVIF])
def test_jpeg_to_format(make_jpeg, tmp_path, fmt):
    src = make_jpeg(size=(800, 600))
    res = run(src, tmp_path / "out", ConversionSettings(formats=[fmt]))
    assert res.status is Status.DONE, res.error
    t = res.targets[0]
    with Image.open(t.dest) as im:
        assert im.format == fmt.value.upper()
        assert im.size == (800, 600)
    assert t.size == t.dest.stat().st_size
    assert res.original_dims == (800, 600)


def test_both_formats_and_quality_affects_size(make_jpeg, tmp_path):
    src = make_jpeg(size=(800, 600))
    lo = run(src, tmp_path / "lo", ConversionSettings(formats=[OutputFormat.WEBP], webp=WebPOptions(quality=20)))
    hi = run(src, tmp_path / "hi", ConversionSettings(formats=[OutputFormat.WEBP], webp=WebPOptions(quality=95)))
    assert lo.targets[0].size < hi.targets[0].size
    both = run(src, tmp_path / "both", ConversionSettings(formats=[OutputFormat.WEBP, OutputFormat.AVIF]))
    assert [t.status for t in both.targets] == [Status.DONE, Status.DONE]


def test_alpha_is_preserved(make_png_alpha, tmp_path):
    src = make_png_alpha()
    res = run(src, tmp_path, ConversionSettings(formats=[OutputFormat.WEBP, OutputFormat.AVIF]))
    for t in res.targets:
        with Image.open(t.dest) as im:
            assert im.mode == "RGBA"
            assert im.getpixel((0, 0))[3] == 0
            assert im.getpixel((100, 75))[3] == 255


def test_webp_lossless_is_pixel_exact(tmp_path):
    src = tmp_path / "exact.png"
    photo((120, 80)).save(src)
    s = ConversionSettings(formats=[OutputFormat.WEBP], webp=WebPOptions(lossless=True))
    res = run(src, tmp_path / "o", s)
    with Image.open(src) as a, Image.open(res.targets[0].dest) as b:
        assert a.convert("RGB").tobytes() == b.convert("RGB").tobytes()


def test_exif_orientation_is_applied(make_jpeg, tmp_path):
    src = make_jpeg(size=(400, 200), orientation=6)  # 90°-os elforgatás
    res = run(src, tmp_path / "o", ConversionSettings())
    assert res.original_dims == (200, 400)
    with Image.open(res.targets[0].dest) as im:
        assert im.size == (200, 400)


def test_metadata_strip_and_keep(make_jpeg, tmp_path):
    src = make_jpeg(gps=True, orientation=6)
    stripped = run(src, tmp_path / "a", ConversionSettings())
    with Image.open(stripped.targets[0].dest) as im:
        assert not im.getexif()

    s = ConversionSettings(metadata=MetadataOptions(keep_exif=True, strip_gps=True))
    kept = run(src, tmp_path / "b", s)
    with Image.open(kept.targets[0].dest) as im:
        exif = im.getexif()
        assert exif.get(ExifTags.Base.Make) == "TestCam"
        assert ExifTags.Base.GPSInfo not in exif
        assert exif.get(ExifTags.Base.Orientation, 1) == 1  # már elforgatva

    s = ConversionSettings(metadata=MetadataOptions(keep_exif=True, strip_gps=False))
    gps = run(src, tmp_path / "c", s)
    with Image.open(gps.targets[0].dest) as im:
        assert im.getexif().get_ifd(ExifTags.IFD.GPSInfo)


def test_resize_is_applied_with_jpeg_draft(make_jpeg, tmp_path):
    src = make_jpeg(size=(1600, 1200))
    s = ConversionSettings(resize=ResizeOptions(mode=ResizeMode.WIDTH, width=300))
    res = run(src, tmp_path, s)
    assert res.output_dims == (300, 225)
    with Image.open(res.targets[0].dest) as im:
        assert im.size == (300, 225)


def test_fill_resize_rotated_jpeg(make_jpeg, tmp_path):
    src = make_jpeg(size=(1600, 1000), orientation=8)
    s = ConversionSettings(resize=ResizeOptions(mode=ResizeMode.FILL, width=200, height=300))
    res = run(src, tmp_path, s)
    assert res.output_dims == (200, 300)


def test_animated_gif_to_animated_webp_and_avif(make_gif, tmp_path):
    src = make_gif(frames=4)
    res = run(src, tmp_path, ConversionSettings(formats=[OutputFormat.WEBP, OutputFormat.AVIF]))
    assert res.frames == 4
    for t in res.targets:
        with Image.open(t.dest) as im:
            assert getattr(im, "n_frames", 1) == 4

    s = ConversionSettings(keep_animation=False)
    still = run(src, tmp_path / "still", s)
    with Image.open(still.targets[0].dest) as im:
        assert getattr(im, "n_frames", 1) == 1


@pytest.mark.parametrize(
    "mode",
    ["1", "L", "LA", "P", "I;16", "I", "F", "CMYK", "RGBA", "YCbCr"],
)
def test_all_modes_normalize(mode):
    base = photo((64, 48))
    if mode == "I;16":
        img = base.convert("L").convert("I").point(lambda v: v * 256).convert("I;16")
    elif mode in ("I", "F"):
        img = base.convert("L").convert(mode)
    else:
        img = base.convert(mode)
    warnings = []
    out, icc = normalize_mode(img, None, ColorProfile.SRGB, warnings)
    assert out.mode in ("L", "RGB", "RGBA")
    assert icc is None
    if mode == "I;16":
        # a 16 bites tartomány helyesen skálázódik, nem "vakul be" fehérre
        assert 60 < sum(out.tobytes()) / (64 * 48) < 200


def test_palette_with_transparency_becomes_rgba():
    img = Image.new("P", (10, 10), 0)
    img.info["transparency"] = 0
    out, _ = normalize_mode(img, None, ColorProfile.SRGB, [])
    assert out.mode == "RGBA"


def test_icc_profile_policies(monkeypatch):
    from webkep.core import converter

    srgb = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    img = photo((32, 32))
    assert normalize_mode(img, srgb, ColorProfile.KEEP, [])[1] == srgb
    assert normalize_mode(img, srgb, ColorProfile.SRGB, [])[1] is None
    assert normalize_mode(img, srgb, ColorProfile.STRIP, [])[1] is None

    # "Nem sRGB" profil szimulálása: a konverziós ágnak RGBA-n is működnie kell.
    monkeypatch.setattr(converter, "_is_srgb", lambda icc: False)
    rgba = img.convert("RGBA")
    rgba.putalpha(Image.new("L", (32, 32), 128))
    out, icc = normalize_mode(rgba, srgb, ColorProfile.SRGB, [])
    assert icc is None
    assert out.mode == "RGBA"
    assert out.getchannel("A").getextrema() == (128, 128)


def test_cmyk_jpeg_converts_to_rgb(tmp_path):
    src = tmp_path / "cmyk.jpg"
    photo((100, 80)).convert("CMYK").save(src, quality=90)
    res = run(src, tmp_path / "o", ConversionSettings())
    assert res.status is Status.DONE
    with Image.open(res.targets[0].dest) as im:
        assert im.mode == "RGB"


def test_target_size_search(make_jpeg, tmp_path):
    src = make_jpeg(size=(1200, 900))
    s = ConversionSettings(target_size_enabled=True, target_size_kb=20, target_min_quality=5)
    s.webp.quality = 95
    res = run(src, tmp_path, s)
    t = res.targets[0]
    assert t.status is Status.DONE
    assert t.size <= 20 * 1024
    assert t.quality is not None and t.quality < 95


def test_target_size_unreachable_reports_note(make_jpeg, tmp_path):
    src = make_jpeg(size=(1200, 900))
    s = ConversionSettings(target_size_enabled=True, target_size_kb=1, target_min_quality=50)
    res = run(src, tmp_path, s)
    t = res.targets[0]
    assert t.status is Status.DONE
    assert "1 KB" in t.note


def test_skip_if_larger(tmp_path):
    # Egy erősen tömörített JPEG-ből a veszteségmentes WebP biztosan nagyobb lesz.
    src = tmp_path / "tiny.jpg"
    photo((300, 200)).save(src, quality=5)
    s = ConversionSettings(skip_if_larger=True, webp=WebPOptions(lossless=True))
    res = run(src, tmp_path / "o", s)
    assert res.status is Status.SKIPPED
    assert res.targets[0].size > src.stat().st_size
    assert not (tmp_path / "o" / "tiny.webp").exists()


def test_corrupt_file_reports_error(tmp_path):
    src = tmp_path / "broken.jpg"
    src.write_bytes(b"not an image at all")
    res = run(src, tmp_path / "o", ConversionSettings())
    assert res.status is Status.FAILED
    assert res.error
    assert not list((tmp_path / "o").glob("*")) if (tmp_path / "o").exists() else True


def test_webp_dimension_limit_falls_back_to_error_but_avif_ok(tmp_path):
    src = tmp_path / "wide.png"
    Image.new("RGB", (17000, 8), "white").save(src)
    res = run(src, tmp_path / "o", ConversionSettings(formats=[OutputFormat.WEBP, OutputFormat.AVIF]))
    webp, avif = res.targets
    assert webp.status is Status.FAILED and "16383" in webp.note
    assert avif.status is Status.DONE


def test_timestamps_preserved(make_jpeg, tmp_path):
    import os

    src = make_jpeg()
    os.utime(src, (1_600_000_000, 1_600_000_000))
    res = run(src, tmp_path / "o", ConversionSettings())
    assert int(res.targets[0].dest.stat().st_mtime) == 1_600_000_000


def test_preview_reuses_prepared(make_jpeg):
    src = make_jpeg()
    s = ConversionSettings()
    data1, prepared = convert_preview(src, s, OutputFormat.WEBP, 50)
    data2, prepared2 = convert_preview(src, s, OutputFormat.WEBP, 90, prepared)
    assert prepared2 is prepared
    assert len(data1) < len(data2)
    assert Image.open(io.BytesIO(data1)).format == "WEBP"


def test_prepare_and_encode_grayscale_avif(tmp_path):
    src = tmp_path / "gray.png"
    photo((64, 64)).convert("L").save(src)
    prepared = prepare_image(src, ConversionSettings())
    data = encode(prepared, OutputFormat.AVIF, ConversionSettings())
    assert Image.open(io.BytesIO(data)).size == (64, 64)


@pytest.mark.skipif(os.name == "nt", reason="POSIX jogosultságok")
def test_output_file_permissions_follow_umask(make_jpeg, tmp_path):
    from webkep.core import converter

    src = make_jpeg()
    res = run(src, tmp_path / "o", ConversionSettings())
    mode = res.targets[0].dest.stat().st_mode & 0o777
    assert mode == 0o666 & ~converter._UMASK


def test_mpo_camera_jpeg_is_not_treated_as_animation(tmp_path):
    src = tmp_path / "camera.jpg"
    main, preview = photo((640, 480)), photo((160, 120))
    main.save(src, "MPO", save_all=True, append_images=[preview], quality=90)
    with Image.open(src) as im:
        assert im.format == "MPO" and im.n_frames == 2
    res = run(src, tmp_path / "o", ConversionSettings())
    assert res.frames == 1
    with Image.open(res.targets[0].dest) as out:
        assert getattr(out, "n_frames", 1) == 1
        assert out.size == (640, 480)


def test_multipage_tiff_uses_first_page(tmp_path):
    src = tmp_path / "pages.tif"
    photo((200, 100)).save(src, save_all=True, append_images=[photo((50, 50))])
    res = run(src, tmp_path / "o", ConversionSettings())
    assert res.frames == 1 and res.output_dims == (200, 100)
