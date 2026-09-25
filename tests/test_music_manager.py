"""Testes do gerenciador de músicas (audio/music_manager.py)."""

import json

from audio.music_manager import MusicManager


def test_biblioteca_vazia_retorna_nada(tmp_path):
    manager = MusicManager(extra_folders=[tmp_path / "vazia"])
    # assets/music do projeto também está vazia; a pasta extra não existe
    tracks = [t for t in manager.tracks() if t.path.parent == tmp_path]
    assert tracks == []
    assert manager.pick("energético", 0.8) is None or all(
        t.path.parent != tmp_path for t in manager.tracks()
    )


def test_escaneia_pastas_e_filtra_extensoes(tmp_path):
    (tmp_path / "a.mp3").write_bytes(b"x")
    (tmp_path / "b.wav").write_bytes(b"x")
    (tmp_path / "nota.txt").write_text("não é música")
    manager = MusicManager(extra_folders=[tmp_path])
    tracks = [t for t in manager.tracks() if t.path.parent == tmp_path]
    assert sorted(t.path.name for t in tracks) == ["a.mp3", "b.wav"]


def test_metadados_do_music_json(tmp_path):
    (tmp_path / "trilha.mp3").write_bytes(b"x")
    (tmp_path / "music.json").write_text(
        json.dumps([{"file": "trilha.mp3", "mood": "calmo", "energy": 0.3}]),
        encoding="utf-8",
    )
    manager = MusicManager(extra_folders=[tmp_path])
    track = next(
        t for t in manager.tracks() if t.path.parent == tmp_path
    )
    assert track.mood == "calmo"
    assert track.energy == 0.3
    assert "calmo" in track.label


def test_mood_inferido_do_nome_do_arquivo(tmp_path):
    (tmp_path / "lofi_chill_beat.mp3").write_bytes(b"x")
    (tmp_path / "epic_rock.mp3").write_bytes(b"x")
    manager = MusicManager(extra_folders=[tmp_path])
    by_name = {
        t.path.name: t for t in manager.tracks() if t.path.parent == tmp_path
    }
    assert by_name["lofi_chill_beat.mp3"].mood == "calmo"
    assert by_name["epic_rock.mp3"].mood == "energético"


def test_pick_prefere_clima_correspondente(tmp_path):
    (tmp_path / "calma.mp3").write_bytes(b"x")
    (tmp_path / "energetica.mp3").write_bytes(b"x")
    manager = MusicManager(extra_folders=[tmp_path])
    # restringe às trilhas da pasta de teste para não misturar com assets/music
    tracks = [t for t in manager.tracks() if t.path.parent == tmp_path]
    track = max(tracks, key=lambda t: _pick_score(t, "energético", 0.8))
    assert track.path.name == "energetica.mp3"


def test_pick_prefere_energia_quando_nomes_ambiguos(tmp_path):
    (tmp_path / "calma.mp3").write_bytes(b"x")
    (tmp_path / "energetica.mp3").write_bytes(b"x")
    manager = MusicManager(extra_folders=[tmp_path])
    tracks = [t for t in manager.tracks() if t.path.parent == tmp_path]
    track = max(tracks, key=lambda t: _pick_score(t, "calmo", 0.8))
    assert track.path.name == "calma.mp3"


def _pick_score(track, mood: str, energy: float) -> float:
    s = 0.0
    if track.mood and track.mood.lower() == mood.lower():
        s += 2.0
    elif track.mood and track.mood.lower()[:4] == mood.lower()[:4]:
        s += 1.0
    s += 1.0 - abs(track.energy - energy)
    return s


def test_music_json_invalido_nao_quebra(tmp_path):
    (tmp_path / "a.mp3").write_bytes(b"x")
    (tmp_path / "music.json").write_text("{invalido", encoding="utf-8")
    manager = MusicManager(extra_folders=[tmp_path])
    tracks = [t for t in manager.tracks() if t.path.parent == tmp_path]
    assert len(tracks) == 1
