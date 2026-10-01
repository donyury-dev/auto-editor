"""Testes da sugestão de pack por IA (Fase 7)."""

from __future__ import annotations

from ai.pack_suggest import (
    build_pack_index,
    build_prompt,
    validate_suggestions,
)


def _index():
    return [
        {"category": "overlays", "name": "money rain", "path": "/p/money.mp4"},
        {"category": "sfx", "name": "cash", "path": "/p/cash.wav"},
        {"category": "luts", "name": "warm sunset", "path": "/p/warm.cube"},
    ]


def test_build_prompt_contains_index_and_transcript():
    prompt = build_prompt("olha o money", _index(), duration=30.0)
    assert "money rain" in prompt
    assert "cash" in prompt
    assert "warm sunset" in prompt
    assert "olha o money" in prompt
    assert "30.0s" in prompt


def test_validate_accepts_only_known_assets():
    raw = [
        {"kind": "overlay", "category": "overlays", "name": "money rain",
         "start": 2.0, "end": 4.0, "reason": "citado"},
        {"kind": "overlay", "category": "overlays", "name": "inexistente",
         "start": 5.0, "end": 6.0},
        {"kind": "banana", "category": "overlays", "name": "money rain",
         "start": 5.0, "end": 6.0},
        {"kind": "lut", "category": "luts", "name": "warm sunset",
         "start": 0, "end": 0},
    ]
    result = validate_suggestions(raw, _index(), duration=30.0)
    assert len(result) == 2
    assert result[0]["path"] == "/p/money.mp4"
    assert result[1]["kind"] == "lut"
    assert result[1]["end"] == 30.0  # LUT cobre o vídeo inteiro


def test_validate_caps_and_dedupes():
    raw = [
        {"kind": "sfx", "category": "sfx", "name": "cash", "start": float(i)}
        for i in range(30)
    ] + [
        {"kind": "sfx", "category": "sfx", "name": "cash", "start": 99.0}
    ]
    result = validate_suggestions(raw, _index(), duration=60.0)
    assert len(result) <= 12
    paths = [r["path"] for r in result]
    assert len(paths) == len(set(paths))


def test_validate_garbage_returns_empty():
    assert validate_suggestions(None, _index(), 10.0) == []
    assert validate_suggestions("texto", _index(), 10.0) == []
    assert validate_suggestions([], [], 10.0) == []


def test_build_pack_index_caps_items():
    items = [
        type("I", (), {"category": "overlays", "name": f"item{i}",
                       "path": f"/p/{i}.mp4"})()
        for i in range(500)
    ]
    index = build_pack_index(items)
    assert len(index) == 400
