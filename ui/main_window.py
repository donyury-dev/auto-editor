"""Janela principal: upload, configuração rápida, execução e progresso.

Fluxo da Fase 2: análise (transcrição + plano de edição em QThread) →
tela de revisão (o usuário aprova/ajusta cada sugestão) → renderização
final em QThread. Nada é renderizado sem revisão.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QDesktopServices, QUrl
from PyQt6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ai.provider_manager import ProviderManager
from config.settings import OUTPUT_DIR, OutputFormat, Settings
from core.pipeline import (
    PipelineContext,
    build_analysis_pipeline,
    build_render_pipeline,
)

logger = logging.getLogger(__name__)

VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}


class AnalysisWorker(QThread):
    """Etapa 1: transcreve e gera o plano de edição (para revisão)."""

    progress = pyqtSignal(float, str, str)
    succeeded = pyqtSignal(object)  # PipelineContext com transcript + edit_plan
    failed = pyqtSignal(str)

    def __init__(self, input_path: Path, settings: Settings, manager, parent=None):
        super().__init__(parent)
        self.input_path = input_path
        self.settings = settings
        self.manager = manager
        self.ctx: PipelineContext | None = None

    def run(self) -> None:
        try:
            ctx = PipelineContext(
                input_path=self.input_path, settings=self.settings
            )
            self.ctx = ctx
            build_analysis_pipeline(self.manager).run(
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
        self.setMinimumSize(720, 560)
        self.settings = Settings.load()
        self.manager = ProviderManager()
        self.worker: QThread | None = None
        self._last_step: str | None = None
        self._build_ui()
        self._build_menu()

    # ------------------------------------------------------------------
    # Construção da interface
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        title = QLabel("Auto Editor — Fase 2 (cortes, zoom e transições)")
        title.setStyleSheet("font-size: 18px; font-weight: bold;")
        subtitle = QLabel(
            "Vídeo → transcrição → sugestões da IA → sua revisão → renderização"
        )
        subtitle.setStyleSheet("color: #666;")
        root.addWidget(title)
        root.addWidget(subtitle)

        file_row = QHBoxLayout()
        self.file_edit = QLineEdit()
        self.file_edit.setPlaceholderText(
            "Arraste um vídeo aqui ou clique em Procurar…"
        )
        browse_btn = QPushButton("Procurar…")
        browse_btn.clicked.connect(self._browse)
        file_row.addWidget(self.file_edit, 1)
        file_row.addWidget(browse_btn)
        root.addLayout(file_row)

        format_row = QHBoxLayout()
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
        format_row.addWidget(QLabel("Formato de saída:"))
        format_row.addWidget(self.format_combo, 1)
        root.addLayout(format_row)

        self.run_btn = QPushButton("Analisar e sugerir edição")
        self.run_btn.setStyleSheet("font-size: 15px; padding: 10px;")
        self.run_btn.clicked.connect(self._run)
        root.addWidget(self.run_btn)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        root.addWidget(self.progress_bar)

        self.status_label = QLabel("Pronto.")
        root.addWidget(self.status_label)

        self.log_box = QPlainTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setMaximumHeight(220)
        root.addWidget(self.log_box)

        bottom = QHBoxLayout()
        self.open_btn = QPushButton("Abrir pasta de saída")
        self.open_btn.setVisible(False)
        self.open_btn.clicked.connect(self._open_output)
        bottom.addStretch(1)
        bottom.addWidget(self.open_btn)
        root.addLayout(bottom)

        self.setAcceptDrops(True)

    def _build_menu(self) -> None:
        menu = self.menuBar().addMenu("&Configurações")
        menu.addAction("Provedores de IA…", self._open_settings)

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
                break

    # ------------------------------------------------------------------
    # Ações
    # ------------------------------------------------------------------

    def _browse(self) -> None:
        exts = " ".join(f"*{e}" for e in sorted(VIDEO_EXTENSIONS))
        path, _ = QFileDialog.getOpenFileName(
            self, "Escolher vídeo", "", f"Vídeos ({exts})"
        )
        if path:
            self.file_edit.setText(path)

    def _open_settings(self) -> None:
        from ui.settings_dialog import SettingsDialog

        dialog = SettingsDialog(self.manager, self.settings, self)
        dialog.exec()

    def _run(self) -> None:
        path = Path(self.file_edit.text().strip())
        if not path.exists() or path.suffix.lower() not in VIDEO_EXTENSIONS:
            QMessageBox.warning(
                self, "Vídeo inválido", "Selecione um arquivo de vídeo válido."
            )
            return

        self.settings.output_format = self.format_combo.currentData()
        self.settings.save()

        self.run_btn.setEnabled(False)
        self.progress_bar.setValue(0)
        self.log_box.clear()
        self._last_step = None
        self.open_btn.setVisible(False)
        self.status_label.setText("Iniciando análise…")

        self.worker = AnalysisWorker(path, self.settings, self.manager)
        self.worker.progress.connect(self._on_progress)
        self.worker.succeeded.connect(self._on_analysis_done)
        self.worker.failed.connect(self._on_failure)
        self.worker.start()

    # ------------------------------------------------------------------
    # Callbacks dos workers
    # ------------------------------------------------------------------

    def _on_analysis_done(self, ctx: PipelineContext) -> None:
        """Análise concluída: abre a tela de revisão (obrigatória)."""
        assert ctx.edit_plan is not None
        from ui.review_dialog import ReviewDialog

        self.log_box.appendPlainText(
            f"> Plano: {len(ctx.edit_plan.cuts)} corte(s), "
            f"{len(ctx.edit_plan.zooms)} zoom(s) — aguardando sua revisão"
        )
        dialog = ReviewDialog(ctx.edit_plan, self)
        if dialog.exec() != ReviewDialog.DialogCode.Accepted:
            self.run_btn.setEnabled(True)
            self.status_label.setText("Revisão cancelada — nada foi renderizado.")
            return

        ctx.edit_plan = dialog.approved_plan()
        self.status_label.setText("Renderizando vídeo final…")
        self.progress_bar.setValue(0)
        self._last_step = None

        self.worker = RenderWorker(ctx)
        self.worker.progress.connect(self._on_progress)
        self.worker.succeeded.connect(self._on_success)
        self.worker.failed.connect(self._on_failure)
        self.worker.start()

    def _on_progress(self, overall: float, step: str, msg: str) -> None:
        self.progress_bar.setValue(int(overall * 100))
        self.status_label.setText(f"{step}: {msg}")
        if step != self._last_step:
            self.log_box.appendPlainText(f"> {step}")
            self._last_step = step

    def _on_success(self, output_path: str) -> None:
        self.progress_bar.setValue(100)
        self.status_label.setText(f"Concluído: {output_path}")
        self.log_box.appendPlainText(f"OK — vídeo exportado: {output_path}")
        self.run_btn.setEnabled(True)
        self.open_btn.setVisible(True)
        QMessageBox.information(
            self, "Pronto", f"Vídeo exportado com sucesso:\n{output_path}"
        )

    def _on_failure(self, error: str) -> None:
        self.run_btn.setEnabled(True)
        self.status_label.setText("Falhou.")
        self.log_box.appendPlainText(f"ERRO: {error}")
        QMessageBox.critical(self, "Erro", f"Falha no processamento:\n{error}")

    def _open_output(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(OUTPUT_DIR)))

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
        event.accept()
