"""Painel lateral de biblioteca de assets (estilo CapCut).

Abas: Mídia, Overlays, Transições, SFX, Música, Texto. Cada item é uma
thumbnail + nome e aceita drag-and-drop para a timeline.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PyQt6.QtCore import Qt, QMimeData, pyqtSignal
from PyQt6.QtGui import QDrag, QImage, QPixmap
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from core.pack_manager import PackManager

logger = logging.getLogger(__name__)


class DraggableThumb(QWidget):
    """Thumbnail com nome, arrastável."""

    def __init__(self, path: Path, label: str, kind: str, parent=None) -> None:
        super().__init__(parent)
        self.path = path
        self.kind = kind
        self.label = label
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        self.thumb = QLabel()
        self.thumb.setFixedSize(72, 72)
        self.thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumb.setStyleSheet(
            "background-color: #1e1e24; border-radius: 6px; color: #8b8b96;"
        )
        self._load_thumb()
        layout.addWidget(self.thumb)

        name = QLabel(label[:22])
        name.setStyleSheet("color: #c4c4ce; font-size: 10px;")
        name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name.setWordWrap(True)
        layout.addWidget(name)

    def _load_thumb(self) -> None:
        try:
            import cv2

            cap = cv2.VideoCapture(str(self.path))
            ok, frame = cap.read()
            cap.release()
            if ok and frame is not None:
                h, w = frame.shape[:2]
                img = QImage(frame.data, w, h, 3 * w, QImage.Format.Format_BGR888)
                pix = QPixmap.fromImage(img).scaled(
                    68, 68,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                self.thumb.setPixmap(pix)
                return
        except Exception:
            pass

        # fallback ícone por extensão
        ext = self.path.suffix.lower()
        icon = "🎬" if ext in {".mp4", ".mov", ".webm", ".mkv"} else (
            "🎵" if ext in {".mp3", ".wav", ".m4a", ".ogg", ".aac"} else (
                "🖼" if ext in {".png", ".jpg", ".jpeg", ".webp", ".gif"} else "📄"
            )
        )
        self.thumb.setText(icon)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            return
        mime = QMimeData()
        mime.setText(f"{self.kind}|{self.path}|{self.label}")
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.setHotSpot(event.position().toPoint())
        drag.exec(Qt.DropAction.CopyAction)


class LibraryPanel(QWidget):
    """Painel esquerdo com abas de assets."""

    itemDoubleClicked = pyqtSignal(str, Path, str)  # kind, path, label

    def __init__(
        self,
        source_video: Path | str | None,
        pack_manager: PackManager | None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        if pack_manager is None:
            from config.settings import Settings
            pack_manager = PackManager(Settings())
        self.pack_manager = pack_manager
        self.source_video = Path(source_video) if source_video else None
        self.setFixedWidth(200)
        self._build_ui()
        self._populate()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        title = QLabel("Biblioteca")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        layout.addWidget(self.tabs, 1)

        self.media_tab = self._wrap(self._make_grid())
        self.overlay_tab = self._wrap(self._make_grid())
        self.transition_tab = self._wrap(self._make_grid())
        self.sfx_tab = self._wrap(self._make_grid())
        self.music_tab = self._wrap(self._make_grid())
        self.text_tab = self._wrap(self._make_grid())

        self.tabs.addTab(self.media_tab, "Mídia")
        self.tabs.addTab(self.overlay_tab, "Overlays")
        self.tabs.addTab(self.transition_tab, "Transições")
        self.tabs.addTab(self.sfx_tab, "SFX")
        self.tabs.addTab(self.music_tab, "Música")
        self.tabs.addTab(self.text_tab, "Texto")

    def _make_grid(self) -> QWidget:
        widget = QWidget()
        widget.setLayout(QVBoxLayout())
        widget.layout().setSpacing(8)
        widget.layout().setAlignment(Qt.AlignmentFlag.AlignTop)
        return widget

    def _wrap(self, widget: QWidget) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(widget)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        return scroll

    def _add_thumb(self, container: QWidget, path: Path, label: str, kind: str) -> None:
        thumb = DraggableThumb(path, label, kind)
        container.layout().addWidget(thumb)
        thumb.mouseDoubleClickEvent = lambda _e: self.itemDoubleClicked.emit(
            kind, path, label
        )

    def _populate(self) -> None:
        # Mídia: vídeo original
        if self.source_video and self.source_video.exists():
            grid = self.media_tab.widget().layout()
            self._add_thumb(grid, self.source_video, "Vídeo original", "video")

        # Overlays/Elementos
        overlay_grid = self.overlay_tab.widget().layout()
        for cat in ("overlays", "efeitos_anuncios", "elementos", "personagens", "emojis", "gifs"):
            for item in self.pack_manager.category_items(cat):
                self._add_thumb(overlay_grid, item.path, item.name, "overlay")

        # Transições
        trans_grid = self.transition_tab.widget().layout()
        for item in self.pack_manager.category_items("transicoes"):
            self._add_thumb(trans_grid, item.path, item.name, "transition")

        # SFX
        sfx_grid = self.sfx_tab.widget().layout()
        for item in self.pack_manager.category_items("sfx"):
            self._add_thumb(sfx_grid, item.path, item.name, "sfx")

        # Música
        music_grid = self.music_tab.widget().layout()
        for item in self.pack_manager.category_items("musica"):
            self._add_thumb(music_grid, item.path, item.name, "music")

        # Texto: fontes do pack
        text_grid = self.text_tab.widget().layout()
        for item in self.pack_manager.category_items("fontes"):
            lbl = QLabel(f"Aa — {item.name[:20]}")
            lbl.setStyleSheet(
                "color: #c4c4ce; font-size: 12px; padding: 8px; "
                "background-color: #1e1e24; border-radius: 6px;"
            )
            text_grid.addWidget(lbl)

        # mensagem vazia amigável
        for tab in (
            self.overlay_tab,
            self.transition_tab,
            self.sfx_tab,
            self.music_tab,
            self.text_tab,
        ):
            grid = tab.widget().layout()
            if grid.count() == 0:
                empty = QLabel("HD externo não encontrado\nou categoria vazia")
                empty.setStyleSheet("color: #666; padding: 20px;")
                empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
                empty.setWordWrap(True)
                grid.addWidget(empty)

    def current_kind(self) -> str:
        idx = self.tabs.currentIndex()
        kinds = ["video", "overlay", "transition", "sfx", "music", "text"]
        return kinds[idx] if 0 <= idx < len(kinds) else "overlay"
