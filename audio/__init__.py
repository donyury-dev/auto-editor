"""Motor de áudio da Fase 4: SFX sintetizados, trilhas e mixagem."""

from audio.mixer import AudioMixer
from audio.music_manager import MusicManager, MusicTrack
from audio.sfx_engine import get_sfx

__all__ = ["AudioMixer", "MusicManager", "MusicTrack", "get_sfx"]
