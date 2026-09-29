import pytest
from PIL import Image

from webkep.core.resize import ResizePlan, apply_resize, plan_resize, sharpen
from webkep.core.settings import Resample, ResizeMode, ResizeOptions


def opts(**kw) -> ResizeOptions:
    o = ResizeOptions(**kw)
    o.validate()
    return o


@pytest.mark.parametrize(
    "size, o, expected",
    [
        ((4000, 3000), opts(mode=ResizeMode.NONE), None),
        ((4000, 3000), opts(mode=ResizeMode.PERCENT, percent=50), (2000, 1500)),
        ((4000, 3000), opts(mode=ResizeMode.PERCENT, percent=100), None),
        ((4000, 3000), opts(mode=ResizeMode.WIDTH, width=1200), (1200, 900)),
        ((4000, 3000), opts(mode=ResizeMode.HEIGHT, height=600), (800, 600)),
        ((3000, 4000), opts(mode=ResizeMode.LONG_EDGE, long_edge=1920), (1440, 1920)),
        ((4000, 3000), opts(mode=ResizeMode.FIT, width=1000, height=1000), (1000, 750)),
        ((3000, 4000), opts(mode=ResizeMode.FIT, width=1000, height=1000), (750, 1000)),
        # nagyítás tiltva
        ((800, 600), opts(mode=ResizeMode.WIDTH, width=1200), None),
        ((800, 600), opts(mode=ResizeMode.PERCENT, percent=150), None),
        # nagyítás engedélyezve
        ((800, 600), opts(mode=ResizeMode.WIDTH, width=1200, allow_upscale=True), (1200, 900)),
        ((800, 600), opts(mode=ResizeMode.PERCENT, percent=150, allow_upscale=True), (1200, 900)),
    ],
)
def test_plan_sizes(size, o, expected):
    plan = plan_resize(*size, o)
    assert (plan.size if plan else None) == expected


def test_fill_crops_center_to_exact_size():
    plan = plan_resize(4000, 3000, opts(mode=ResizeMode.FILL, width=400, height=400))
    assert plan.size == (400, 400)
    l, t, r, b = plan.crop
    assert t == 0 and b == 1
    assert l == pytest.approx(0.125) and r == pytest.approx(0.875)


def test_fill_without_upscale_keeps_aspect_at_native_resolution():
    plan = plan_resize(300, 200, opts(mode=ResizeMode.FILL, width=400, height=400))
    assert plan.size == (200, 200)


def test_apply_resize_and_crop():
    img = Image.new("RGB", (400, 200), "red")
    img.paste((0, 0, 255), (0, 0, 100, 200))  # bal szél kék – a vágás eltávolítja
    out = apply_resize(img, plan_resize(400, 200, opts(mode=ResizeMode.FILL, width=100, height=100)), Resample.LANCZOS)
    assert out.size == (100, 100)
    assert out.getpixel((2, 50))[0] > 200  # piros, nem kék


def test_apply_none_returns_same_object():
    img = Image.new("RGB", (10, 10))
    assert apply_resize(img, None, Resample.LANCZOS) is img
    assert apply_resize(img, ResizePlan((10, 10)), Resample.LANCZOS) is img


def test_sharpen_keeps_alpha():
    img = Image.new("RGBA", (50, 50), (100, 100, 100, 0))
    img.paste((200, 200, 200, 255), (10, 10, 40, 40))
    out = sharpen(img, 80)
    assert out.mode == "RGBA"
    assert out.getchannel("A").getextrema() == (0, 255)
    assert out.getpixel((0, 0))[3] == 0
