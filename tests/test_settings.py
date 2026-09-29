import json

from webkep.core.config import AppState, load_state, save_state
from webkep.core.presets import builtin_presets
from webkep.core.settings import ConversionSettings, OutputFormat, ResizeMode
from webkep.i18n import fmt_bytes, fmt_duration, fmt_percent, set_language, tr


def test_roundtrip():
    s = ConversionSettings(formats=[OutputFormat.AVIF, OutputFormat.WEBP])
    s.resize.mode = ResizeMode.FILL
    s.webp.quality = 42
    again = ConversionSettings.from_dict(json.loads(json.dumps(s.to_dict())))
    assert again == s


def test_from_dict_is_tolerant():
    s = ConversionSettings.from_dict(
        {
            "formats": ["webp", "gif"],  # érvénytelen elem -> alapértelmezés
            "webp": {"quality": 150, "method": "9", "unknown": 1},
            "avif": {"subsampling": "9:9:9"},
            "resize": {"mode": "nonsense", "width": -5},
            "garbage": True,
        }
    )
    assert s.formats == [OutputFormat.WEBP]
    assert s.webp.quality == 100 and s.webp.method == 6
    assert s.avif.subsampling == "4:2:0"
    assert s.resize.mode is ResizeMode.NONE and s.resize.width == 1


def test_app_state_persistence(tmp_path):
    state = AppState(input_dir="C:/képek", language="en")
    state.conversion.webp.quality = 70
    state.user_presets["Saját"] = state.conversion.to_dict()
    path = tmp_path / "s.json"
    assert save_state(state, path)
    loaded = load_state(path)
    assert loaded.input_dir == "C:/képek"
    assert loaded.language == "en"
    assert loaded.conversion.webp.quality == 70
    assert "Saját" in loaded.user_presets


def test_corrupt_state_falls_back(tmp_path):
    path = tmp_path / "s.json"
    path.write_text("{not json", encoding="utf-8")
    assert load_state(path) == AppState()


def test_presets_are_valid_and_translated():
    keys = set()
    for p in builtin_presets():
        assert p.settings.formats
        assert p.name != f"preset.{p.key}"
        assert p.description != f"preset.{p.key}.desc"
        keys.add(p.key)
    assert "balanced" in keys


def test_formatting_helpers():
    set_language("hu")
    assert fmt_bytes(512) == "512 B"
    assert fmt_bytes(1536) == "1,5 KB"
    assert fmt_percent(0.642, 1, signed=True) == "-64,2%"
    assert fmt_percent(-0.1, 0, signed=True) == "+10%"
    assert fmt_duration(83) == "1:23"
    assert fmt_duration(4.26) == "4,3 mp"
    assert fmt_duration(42) == "42 mp"
    assert fmt_duration(3723) == "1:02:03"
    set_language("en")
    assert fmt_bytes(1536) == "1.5 KB"
    assert tr("status.done") == "Done"


def test_all_translations_have_both_languages():
    from webkep._strings import STRINGS

    for key, value in STRINGS.items():
        assert isinstance(value, tuple) and len(value) == 2, key
        assert all(isinstance(v, str) and v for v in value), key
