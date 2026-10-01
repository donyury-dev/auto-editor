"""Teste de regressão: o modelo VAD do faster-whisper deve estar disponível.

No empacotamento PyInstaller os assets do faster-whisper precisam ser
incluídos explicitamente; este teste falha se o arquivo .onnx do Silero
VAD não for encontrado.
"""

from __future__ import annotations


def test_silero_vad_asset_exists():
    from faster_whisper.vad import get_vad_model

    model = get_vad_model()
    assert model is not None
    assert hasattr(model, "session")


def test_vad_asset_file_is_readable():
    import os

    from faster_whisper.utils import get_assets_path

    path = os.path.join(get_assets_path(), "silero_vad_v6.onnx")
    assert os.path.exists(path)
    assert os.path.getsize(path) > 1_000_000
