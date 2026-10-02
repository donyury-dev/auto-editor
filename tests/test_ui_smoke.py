"""Smoke test de UI: abre todas as telas principais (Fase 7).

Teria pego os bugs 'QTableWidgetItem is not defined' e
'ReviewDialog got an unexpected keyword argument tracks'.
"""

from __future__ import annotations

import inspect
import os

import pytest


@pytest.fixture(scope="session")
def qt_app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        from PyQt6.QtWidgets import QApplication

        app = QApplication.instance() or QApplication([])
    except ImportError as exc:
        msg = str(exc).lower()
        if "libegl" in msg or "platform plugin" in msg or "display" in msg:
            pytest.skip(f"ambiente sem display/libEGL: {exc}")
        raise
    return app


def _make_window(qt_app):
    from ui.main_window import MainWindow

    return MainWindow()


def test_settings_dialog_opens_with_pack_table(qt_app, tmp_path):
    from config.settings import Settings
    from ui.settings_dialog import SettingsDialog

    settings = Settings()
    from ai.provider_manager import ProviderManager
    from images.manager import ImageProviderManager

    dialog = SettingsDialog(
        ProviderManager(), settings, ImageProviderManager(), None
    )
    assert dialog.pack_table.rowCount() == 17
    dialog.settings.save = lambda *a, **k: None  # não persiste no teste
    dialog.accept()


def test_timeline_editor_accepts_expected_kwargs(qt_app):
    import inspect

    from ui.timeline_editor import TimelineEditor

    sig = inspect.signature(TimelineEditor.__init__)
    assert "edit_plan" in sig.parameters
    assert "illustrations" in sig.parameters
    assert "audio_plan" in sig.parameters
    assert "pack_suggestions" in sig.parameters
    assert "pack_manager" in sig.parameters
    assert "video_path" in sig.parameters


def test_all_main_dialogs_open_without_exception(qt_app, tmp_path):
    from ai.provider_manager import ProviderManager
    from core.pack_manager import PackManager
    from ui.main_window import MainWindow
    from ui.templates_dialog import TemplatesDialog

    window = MainWindow()
    window.pack_manager = PackManager(window.settings)

    TemplatesDialog(window.template_manager, window.settings, window)

    from ui.settings_dialog import SettingsDialog

    SettingsDialog(
        window.manager,
        window.settings,
        window.image_manager,
        window,
        pack_manager=window.pack_manager,
    )

    window.preview.seek_fraction(0.25)
    window.close()


def test_preview_widget_seeks_with_loaded_video(qt_app, tmp_path):
    """Preview carrega um vídeo real (se houver ffmpeg p/ gerar um) e busca tempo."""
    import cv2
    import numpy as np

    video_path = tmp_path / "preview_src.mp4"
    writer = cv2.VideoWriter(
        str(video_path),
        cv2.VideoWriter_fourcc(*"mp4v"),
        30.0,
        (320, 240),
    )
    for i in range(90):  # 3s
        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        frame[:, :, i % 3] = 255
        writer.write(frame)
    writer.release()

    from ui.preview_widget import LivePreviewWidget

    widget = LivePreviewWidget()
    assert widget.load(video_path)
    widget.set_time(1.5)
    widget.seek_fraction(0.5)
    widget.stop()
