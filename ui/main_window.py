"""Janela principal — redesign Fase 7 (estilo CapCut, leve).

Barra lateral com navegação por etapas + área de trabalho. Fluxo:
vídeo → análise (QThread) → tela de revisão (obrigatória) → render
(QThread). Nada é renderizado sem revisão.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PyQt6.QtCore import QThread, QUrl, Qt, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ai.provider_manager import ProviderManager
from config.settings import OUTPUT_DIR, OutputFormat, Settings
from core.pack_manager import PackManager
from core.pipeline import (
    PipelineContext,
    build_analysis_pipeline,
    build_render_pipeline,
)
from core.templates import TemplateManager, ensure_caption_preset
from images.manager import ImageProviderManager
from ui.preview_widget import LivePreviewWidget

logger = logging.getLogger(__name__)

VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}


class AnalysisWorker(QThread):
    """Etapa 1: transcreve, gera o plano de edição e as sugestões."""

    progress = pyqtSignal(float, str, str)
    succeeded = pyqtSignal(object)  # PipelineContext
    failed = pyqtSignal(str)

    def __init__(
        self,
        input_path: Path,
        settings: Settings,
        manager,
        image_manager,
        music_manager,
        pack_manager,
        parent=None,
    ):
        super().__init__(parent)
        self.input_path = input_path
        self.settings = settings
        self.manager = manager
        self.image_manager = image_manager
        self.music_manager = music_manager
        self.pack_manager = pack_manager
        self.ctx: PipelineContext | None = None

    def run(self) -> None:
        try:
            ctx = PipelineContext(
                input_path=self.input_path, settings=self.settings
            )
            self.ctx = ctx
            build_analysis_pipeline(
                self.manager,
                self.image_manager,
                self.music_manager,
                self.pack_manager,
            ).run(
                ctx,
                lambda overall, step, msg: self.progress.emit(overall, step, msg),
            )
            self.succeeded.emit(ctx)
        except Exception as exc:
            logger.exception("Análise falhou")
            self.failed.emit(str(exc))


class RenderWorker(QThread):
    """Etapa 2: aplica o plano APROVADO e renderiza o vídeo final."""

    progress = pyqtSignal(float, str, str)
    succeeded = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, ctx: PipelineContext, parent=None):
        super().__init__(parent)
        self.ctx = ctx

    def run(self) -> None:
        try:
            build_render_pipeline().run(
                self.ctx,
                lambda overall, step, msg: self.progress.emit(overall, step, msg),
            )
            self.succeeded.emit(str(self.ctx.output_path))
        except Exception as exc:
            logger.exception("Renderização falhou")
            self.failed.emit(str(exc))


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Auto Editor — Edição viral com IA")
        self.setMinimumSize(880, 620)
        self.settings = Settings.load()
        self.manager = ProviderManager()
        self.image_manager = ImageProviderManager()
        self.template_manager = TemplateManager()
        self.pack_manager = PackManager(self.settings)
        for t in self.template_manager.list_templates():
            ensure_caption_preset(t)
        self.worker: QThread | None = None
        self._last_step: str | None = None
        self._last_output_path: Path | None = None
        self._ctx: PipelineContext | None = None
        self._build_ui()
        self._build_menu()

    # ------------------------------------------------------------------
    # Construção da interface
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ---- barra lateral ------------------------------------------------
        sidebar = QFrame()
        sidebar.setFixedWidth(190)
        sidebar.setObjectName("sidebar")
        side_layout = QVBoxLayout(sidebar)
        side_layout.setContentsMargins(12, 18, 12, 12)
        side_layout.setSpacing(4)

        logo = QLabel("Auto Editor")
        logo.setObjectName("appTitle")
        side_layout.addWidget(logo)
        side_layout.addSpacing(14)

        self.nav_new = QPushButton("Novo vídeo")
        self.nav_progress = QPushButton("Andamento")
        for btn in (self.nav_new, self.nav_progress):
            btn.setObjectName("navButton")
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            side_layout.addWidget(btn)
        self.nav_new.setChecked(True)

        side_layout.addStretch(1)
        self.template_btn = QPushButton("Template de estilo…")
        self.template_btn.setObjectName("navButton")
        self.template_btn.clicked.connect(self._open_templates)
        side_layout.addWidget(self.template_btn)
        self.settings_btn = QPushButton("Configurações")
        self.settings_btn.setObjectName("navButton")
        self.settings_btn.clicked.connect(self._open_settings)
        side_layout.addWidget(self.settings_btn)

        self.template_label = QLabel("")
        self.template_label.setStyleSheet(
            "color: #8b8b96; font-size: 11px; padding-left: 6px;"
        )
        side_layout.addWidget(self.template_label)
        if self.settings.active_template_id:
            active = self.template_manager.get(self.settings.active_template_id)
            if active:
                self.template_label.setText(active.name)

        root.addWidget(sidebar)

        # separador vertical
        line = QFrame()
        line.setFrameShape(QFrame.Shape.VLine)
        line.setStyleSheet("color: #2e2e38;")
        root.addWidget(line)

        # ---- área de trabalho --------------------------------------------
        self.pages = QStackedWidget()
        root.addWidget(self.pages, 1)
        self.pages.addWidget(self._build_new_video_page())
        self.pages.addWidget(self._build_progress_page())

        self.nav_new.clicked.connect(lambda: self._switch_page(0))
        self.nav_progress.clicked.connect(lambda: self._switch_page(1))
        self.setAcceptDrops(True)

    def _page_title(self, text: str, subtitle: str) -> QVBoxLayout:
        layout = QVBoxLayout()
        title = QLabel(text)
        title.setObjectName("appTitle")
        subtitle_label = QLabel(subtitle)
        subtitle_label.setObjectName("appSubtitle")
        layout.addWidget(title)
        layout.addWidget(subtitle_label)
        layout.addSpacing(10)
        return layout

    def _build_new_video_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 18, 24, 18)
        layout.setSpacing(10)
        layout.addLayout(
            self._page_title(
                "Novo vídeo",
                "Vídeo → transcrição → sugestões da IA → sua revisão → vídeo final",
            )
        )

        file_label = QLabel("Vídeo de origem")
        file_label.setObjectName("sectionTitle")
        layout.addWidget(file_label)
        file_row = QHBoxLayout()
        self.file_edit = QLineEdit()
        self.file_edit.setPlaceholderText(
            "Arraste um vídeo aqui ou clique em Procurar…"
        )
        browse_btn = QPushButton("Procurar…")
        browse_btn.clicked.connect(self._browse)
        file_row.addWidget(self.file_edit, 1)
        file_row.addWidget(browse_btn)
        layout.addLayout(file_row)
        # preview carrega sozinho assim que um vídeo válido é escolhido
        self.file_edit.textChanged.connect(self._on_file_text_changed)

        options_row = QHBoxLayout()
        format_box = QVBoxLayout()
        format_label = QLabel("Formato de saída")
        format_label.setObjectName("sectionTitle")
        format_box.addWidget(format_label)
        self.format_combo = QComboBox()
        self.format_combo.addItem(
            "Vertical 9:16 (Reels/TikTok/Shorts)", OutputFormat.VERTICAL
        )
        self.format_combo.addItem(
            "Horizontal 16:9 (YouTube)", OutputFormat.HORIZONTAL
        )
        self.format_combo.addItem("Manter formato original", OutputFormat.ORIGINAL)
        index = self.format_combo.findData(self.settings.output_format)
        if index >= 0:
            self.format_combo.setCurrentIndex(index)
        format_box.addWidget(self.format_combo)
        options_row.addLayout(format_box, 1)

        illus_box = QVBoxLayout()
        illus_label = QLabel("Destaques em imagem")
        illus_label.setObjectName("sectionTitle")
        illus_box.addWidget(illus_label)
        self.illus_combo = QComboBox()
        for prov in self.image_manager.describe_providers():
            self.illus_combo.addItem(prov["label"], prov["id"])
        index = self.illus_combo.findData(self.settings.illustration_provider)
        if index >= 0:
            self.illus_combo.setCurrentIndex(index)
        illus_box.addWidget(self.illus_combo)
        options_row.addLayout(illus_box, 1)
        layout.addLayout(options_row)

        preview_label = QLabel("Preview do vídeo")
        preview_label.setObjectName("sectionTitle")
        layout.addWidget(preview_label)
        self.preview = LivePreviewWidget()
        layout.addWidget(self.preview, 1)

        self.run_btn = QPushButton("Analisar e sugerir edição")
        self.run_btn.setObjectName("accent")
        self.run_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.run_btn.clicked.connect(self._run)
        layout.addWidget(self.run_btn)

        return page

    def _build_progress_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 18, 24, 18)
        layout.setSpacing(10)
        layout.addLayout(
            self._page_title("Andamento", "Acompanhe a análise e a renderização")
        )

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        layout.addWidget(self.progress_bar)

        self.status_label = QLabel("Pronto.")
        layout.addWidget(self.status_label)

        log_label = QLabel("Detalhes")
        log_label.setObjectName("sectionTitle")
        layout.addWidget(log_label)
        self.log_box = QPlainTextEdit()
        self.log_box.setReadOnly(True)
        layout.addWidget(self.log_box, 1)

        bottom = QHBoxLayout()
        self.open_btn = QPushButton("Abrir pasta de saída")
        self.open_btn.setVisible(False)
        self.open_btn.clicked.connect(self._open_output)
        bottom.addStretch(1)
        bottom.addWidget(self.open_btn)
        layout.addLayout(bottom)
        return page

    def _switch_page(self, index: int) -> None:
        self.pages.setCurrentIndex(index)
        self.nav_new.setChecked(index == 0)
        self.nav_progress.setChecked(index == 1)

    def _build_menu(self) -> None:
        menu = self.menuBar().addMenu("&Configurações")
        menu.addAction("Provedores de IA…", self._open_settings)
        menu.addAction("Templates de estilo…", self._open_templates)

    def _open_templates(self) -> None:
        from ui.templates_dialog import TemplatesDialog

        dialog = TemplatesDialog(
            self.template_manager, self.settings, self
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            t = dialog.selected_template
            if t:
                self.template_label.setText(t.name)
                self._log(f"Template aplicado: {t.name}")

    # ------------------------------------------------------------------
    # Arrastar e soltar
    # ------------------------------------------------------------------

    def dragEnterEvent(self, event) -> None:  # noqa: N802 (API Qt)
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802 (API Qt)
        for url in event.mimeData().urls():
            path = Path(url.toLocalFile())
            if path.suffix.lower() in VIDEO_EXTENSIONS:
                self.file_edit.setText(str(path))
                self._load_preview(path)
                break

    # ------------------------------------------------------------------
    # Ações
    # ------------------------------------------------------------------

    def _load_preview(self, path: Path) -> None:
        if not self.preview.load(path):
            self.preview.clear()

    def _on_file_text_changed(self, text: str) -> None:
        path = Path(text.strip())
        if path.exists() and path.suffix.lower() in VIDEO_EXTENSIONS:
            self._load_preview(path)

    def _browse(self) -> None:
        exts = " ".join(f"*{e}" for e in sorted(VIDEO_EXTENSIONS))
        path, _ = QFileDialog.getOpenFileName(
            self, "Escolher vídeo", "", f"Vídeos ({exts})"
        )
        if path:
            self.file_edit.setText(path)
            self._load_preview(Path(path))

    def _open_settings(self) -> None:
        from ui.settings_dialog import SettingsDialog

        dialog = SettingsDialog(
            self.manager,
            self.settings,
            self.image_manager,
            self,
            pack_manager=self.pack_manager,
        )
        dialog.exec()

    def _run(self) -> None:
        path = Path(self.file_edit.text().strip())
        if not path.exists() or path.suffix.lower() not in VIDEO_EXTENSIONS:
            QMessageBox.warning(
                self, "Vídeo inválido", "Selecione um arquivo de vídeo válido."
            )
            return

        self.settings.output_format = self.format_combo.currentData()
        self.settings.illustration_provider = self.illus_combo.currentData()
        self.settings.save()
        self.pack_manager = PackManager(self.settings)

        self.run_btn.setEnabled(False)
        self.progress_bar.setValue(0)
        self.log_box.clear()
        self._last_step = None
        self.open_btn.setVisible(False)
        self.status_label.setText("Iniciando análise…")
        self._switch_page(1)
        self.preview.pause()

        from audio.music_manager import MusicManager

        music_folders = [self.settings.music_dir] if self.settings.music_dir else []
        music_folders += [
            str(f) for f in self.pack_manager.music_folders()
        ]
        self.worker = AnalysisWorker(
            path,
            self.settings,
            self.manager,
            self.image_manager,
            MusicManager(music_folders),
            self.pack_manager,
        )
        self.worker.progress.connect(self._on_progress)
        self.worker.succeeded.connect(self._on_analysis_done)
        self.worker.failed.connect(self._on_failure)
        self.worker.start()

    # ------------------------------------------------------------------
    # Callbacks dos workers
    # ------------------------------------------------------------------

    def _on_analysis_done(self, ctx: PipelineContext) -> None:
        """Análise concluída: abre o editor de timeline (obrigatório)."""
        assert ctx.edit_plan is not None
        from ui.timeline_editor import TimelineEditor

        self._log(
            f"> Plano: {len(ctx.edit_plan.cuts)} corte(s), "
            f"{len(ctx.edit_plan.zooms)} zoom(s), "
            f"{len(ctx.illustrations)} destaque(s), "
            f"{len(ctx.pack_suggestions)} sugestão(ões) do pack, "
            f"{len(ctx.audio_plan.sfx) if ctx.audio_plan else 0} efeito(s) "
            "— abrindo editor de timeline"
        )

        dialog = TimelineEditor(
            ctx.edit_plan,
            ctx.illustrations,
            ctx.audio_plan,
            ctx.pack_suggestions,
            self.pack_manager,
            ctx.input_path,
            parent=self,
        )
        if dialog.exec() != TimelineEditor.DialogCode.Accepted:
            self.run_btn.setEnabled(True)
            self.status_label.setText("Edição cancelada — nada foi renderizado.")
            self._switch_page(0)
            return

        ctx.edit_plan = dialog.approved_plan()
        ctx.illustrations = dialog.approved_illustrations()
        ctx.audio_plan = dialog.approved_audio()
        ctx.pack_suggestions = dialog.approved_pack()
        self.run_btn.setEnabled(False)
        self.status_label.setText("Renderizando vídeo final…")
        self.progress_bar.setValue(0)
        self._last_step = None

        self.worker = RenderWorker(ctx)
        self.worker.progress.connect(self._on_progress)
        self.worker.succeeded.connect(self._on_success)
        self.worker.failed.connect(self._on_failure)
        self.worker.start()

    @property
    def _review_tracks(self):
        from audio.music_manager import MusicManager

        folders = [self.settings.music_dir] if self.settings.music_dir else []
        folders += [str(f) for f in self.pack_manager.music_folders()]
        return MusicManager(folders).tracks()

    def _on_progress(self, overall: float, step: str, msg: str) -> None:
        self.progress_bar.setValue(int(overall * 100))
        self.status_label.setText(f"{step}: {msg}")
        if step != self._last_step:
            self._log(f"> {step}")
            self._last_step = step
        # preview acompanha a renderização em tempo real
        if step == "Renderização" and msg.endswith("%"):
            try:
                pct = float(msg.rsplit(" ", 1)[-1].rstrip("%")) / 100.0
                self.preview.seek_fraction(pct)
            except (ValueError, IndexError):
                pass

    def _on_success(self, output_path: str) -> None:
        self._last_output_path = Path(output_path)
        self.progress_bar.setValue(100)
        self.status_label.setText(f"Concluído: {output_path}")
        self.status_label.setObjectName("statusOk")
        self.status_label.setStyleSheet("color: #34d1c0;")
        self._log(f"OK — vídeo exportado: {output_path}")
        self.run_btn.setEnabled(True)
        self.open_btn.setVisible(True)
        # fluxo "conferir antes de postar": play do vídeo final, e só
        # depois o usuário decide abrir a pasta / postar.
        self._show_final_review(Path(output_path))

    def _show_final_review(self, output_path: Path) -> None:
        """Diálogo com o vídeo final em play para conferência."""
        from ui.preview_widget import LivePreviewWidget

        dlg = QDialog(self)
        dlg.setWindowTitle("Conferir vídeo final")
        dlg.resize(520, 640)
        v = QVBoxLayout(dlg)
        player = LivePreviewWidget()
        v.addWidget(player, 1)
        row = QHBoxLayout()
        open_folder = QPushButton("Abrir pasta (extrair para postar)")
        open_folder.setObjectName("accent")
        close = QPushButton("Fechar")
        row.addStretch(1)
        row.addWidget(open_folder)
        row.addWidget(close)
        v.addLayout(row)

        def _open() -> None:
            QDesktopServices.openUrl(
                QUrl.fromLocalFile(str(output_path.parent))
            )

        open_folder.clicked.connect(_open)
        close.clicked.connect(dlg.reject)
        if not player.load(output_path):
            player.clear()
        else:
            player.play()
        dlg.exec()
        player.stop()

    def _on_failure(self, error: str) -> None:
        self.run_btn.setEnabled(True)
        self.status_label.setText("Falhou.")
        self.status_label.setStyleSheet("color: #ff6b6b;")
        self._log(f"ERRO: {error}")
        QMessageBox.critical(self, "Erro", f"Falha no processamento:\n{error}")

    def _log(self, text: str) -> None:
        self.log_box.appendPlainText(text)

    def _open_output(self) -> None:
        target = OUTPUT_DIR
        if self._last_output_path is not None:
            target = self._last_output_path.parent
        elif self.settings.output_dir:
            target = Path(self.settings.output_dir)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))

    # ------------------------------------------------------------------
    # Fechamento
    # ------------------------------------------------------------------

    def closeEvent(self, event) -> None:  # noqa: N802 (API Qt)
        if self.worker is not None and self.worker.isRunning():
            answer = QMessageBox.question(
                self,
                "Processamento em andamento",
                "A edição ainda está rodando. Encerrar mesmo assim "
                "(o vídeo final será perdido)?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        self.preview.stop()
        event.accept()
