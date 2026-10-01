"""Testes do pack externo de assets (Fase 7)."""

from __future__ import annotations

from pathlib import Path

from core.pack_manager import (
    PACK_CATEGORIES,
    PackManager,
    PackSuggestion,
    suggestions_from_json,
    suggestions_to_json,
)


def _make_settings(root: Path | None):
    from config.settings import Settings

    s = Settings()
    s.pack_root = str(root) if root else ""
    s.pack_folders = {}
    return s


def _make_pack(root: Path) -> None:
    (root / "1 - Efeitos Usados nos Anúncios").mkdir(parents=True)
    (root / "3 - Overlays").mkdir(parents=True)
    (root / "6 - Sound Effects").mkdir(parents=True)
    (root / "13 - Fontes").mkdir(parents=True)
    (root / "14 - LUTS").mkdir(parents=True)
    (root / "3 - Overlays" / "money rain.mp4").write_bytes(b"x")
    (root / "3 - Overlays" / "seta animada.webm").write_bytes(b"x")
    (root / "6 - Sound Effects" / "cash.wav").write_bytes(b"x")
    (root / "13 - Fontes" / "MinhaFonte.ttf").write_bytes(b"x")
    (root / "14 - LUTS" / "warm sunset.cube").write_bytes(b"x")
    (root / "14 - LUTS" / "cool cinematic.cube").write_bytes(b"x")


def test_scan_auto_detects_capcut_pack_folders(tmp_path):
    root = tmp_path / "CapCut Pack"
    _make_pack(root)
    manager = PackManager(_make_settings(root))
    index = manager.scan()

    assert len(index["overlays"]) == 2
    assert len(index["sfx"]) == 1
    assert len(index["fontes"]) == 1
    assert len(index["luts"]) == 2
    assert manager.missing_categories() == []


def test_scan_with_hd_disconnected_falls_back_cleanly(tmp_path):
    # configuração aponta para pasta que NÃO existe (HD desconectado)
    settings = _make_settings(None)
    settings.pack_folders = {"overlays": str(tmp_path / "nao-existe")}
    manager = PackManager(settings)
    index = manager.scan()

    assert index["overlays"] == []
    assert "Overlays" in manager.missing_categories()
    # nunca lança exceção; demais categorias apenas vazias
    assert index["luts"] == []


def test_suggest_usages_matches_asset_names_to_speech(tmp_path):
    root = tmp_path / "pack"
    _make_pack(root)
    manager = PackManager(_make_settings(root))

    words = [
        {"start": 1.0, "end": 1.5, "text": "olha"},
        {"start": 1.6, "end": 2.2, "text": "o"},
        {"start": 2.3, "end": 3.0, "text": "money"},
        {"start": 5.0, "end": 5.8, "text": "cash"},
    ]
    suggestions = manager.suggest_usages(words, duration=10.0, mood="energético")
    kinds = {s.kind for s in suggestions}
    assert "overlay" in kinds
    assert "sfx" in kinds
    assert "lut" in kinds  # sempre sugere 1 LUT quando há LUTs no pack
    # clima energético → prefere LUT "warm"
    lut = next(s for s in suggestions if s.kind == "lut")
    assert "warm" in lut.path.name


def test_suggest_usages_empty_pack_returns_lut_only_if_any(tmp_path):
    manager = PackManager(_make_settings(None))
    words = [{"start": 1.0, "end": 2.0, "text": "qualquer"}]
    assert manager.suggest_usages(words, duration=5.0) == []


def test_suggestion_json_roundtrip(tmp_path):
    suggestion = PackSuggestion(
        kind="overlay",
        path=Path("/tmp/x.mp4"),
        category="overlays",
        start=1.0,
        end=3.5,
        reason="teste",
    )
    path = tmp_path / "sug.json"
    suggestions_to_json([suggestion], path)
    loaded = suggestions_from_json(path)
    assert len(loaded) == 1
    assert loaded[0].kind == "overlay"
    assert loaded[0].path == Path("/tmp/x.mp4")
    assert abs(loaded[0].end - 3.5) < 1e-6


def test_settings_pack_fields_roundtrip(tmp_path):
    from config.settings import Settings

    path = tmp_path / "settings.json"
    s = Settings()
    s.pack_root = "E:/Packs CapCut/CapCut Pack"
    s.pack_folders = {"overlays": "E:/pack/overlays"}
    s.save(path)

    loaded = Settings.load(path)
    assert loaded.pack_root == "E:/Packs CapCut/CapCut Pack"
    assert loaded.pack_folders == {"overlays": "E:/pack/overlays"}


def test_all_17_pack_categories_defined():
    expected = {
        "efeitos_anuncios", "backgrounds", "overlays", "transicoes",
        "light_leaks", "sfx", "musica", "elementos", "personagens",
        "emojis", "icones", "gifs", "fontes", "luts", "memes", "setas",
        "stock",
    }
    assert set(PACK_CATEGORIES) == expected
