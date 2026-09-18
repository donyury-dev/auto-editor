"""Testes do mixer de áudio (audio/mixer.py) — construção de filtros."""

from core.audio_plan import AudioPlan, SfxEvent
from audio.mixer import VOICE_TARGET_LUFS, build_audio_filter


def test_voz_normalizada_antes_do_ducking():
    plan = AudioPlan(music_path="x.mp3", music_volume=0.25, normalize_voice=True)
    fc = build_audio_filter(plan, [], 0, has_voice=True)
    # loudnorm na voz vem ANTES do sidechaincompress da música
    assert fc.index("loudnorm") < fc.index("sidechaincompress")
    assert f"I={VOICE_TARGET_LUFS}" in fc
    assert "sidechaincompress" in fc


def test_sem_musica_nao_tem_sidechain():
    plan = AudioPlan(normalize_voice=True)
    fc = build_audio_filter(plan, [], 0, has_voice=True)
    assert "sidechaincompress" not in fc
    assert "loudnorm" in fc


def test_sfx_com_adelay_e_amix():
    plan = AudioPlan(normalize_voice=False)
    events = [
        SfxEvent(kind="whoosh", timestamp=1.5),
        SfxEvent(kind="ding", timestamp=10.0),
    ]
    fc = build_audio_filter(plan, events, len(events), has_voice=True)
    assert "adelay=1500:all=1" in fc
    assert "adelay=10000:all=1" in fc
    assert "amix=inputs=3" in fc  # voz + 2 efeitos
    assert "alimiter" in fc


def test_sem_voz_gera_silencio_base():
    plan = AudioPlan(music_path="x.mp3", normalize_voice=False)
    fc = build_audio_filter(plan, [], 0, has_voice=False, duration=12.0)
    assert "anullsrc" in fc
    assert "atrim=duration=12.000" in fc


def test_volume_da_musica_aplicado():
    plan = AudioPlan(music_path="x.mp3", music_volume=0.4)
    fc = build_audio_filter(plan, [], 0, has_voice=True)
    assert "volume=0.400" in fc
