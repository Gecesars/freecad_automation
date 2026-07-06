from __future__ import annotations

import json
import inspect
import subprocess
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtGui import QAction, QColor, QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QApplication,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSlider,
    QSplitter,
    QStyle,
    QTabWidget,
    QToolBar,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.agent import PromptAgent
from app.diagnostics.failure_package import create_failure_package
from app.doctor import run_doctor
from app.freecad_runner import find_freecad_executable, run_macro
from app.job_manager import CadJobResult, JobManager
from app.importers.dwg_importer import DwgImporter
from app.importers.dxf_importer import DxfImporter
from app.importers.import_report import ImportReport
from app.importers.mesh_importer import MeshImporter
from app.importers.step_importer import StepImporter
from app.importers.svg_importer import SvgImporter
from app.models import GeneratedDesign, RunResult
from app.rag_ingest_v2 import ingest_v2
from app.rag_store import LocalRagStore
from app.settings import DIAGNOSTICS_DIR, MACROS_DIR, OUTPUT_DIR, RAG_DIR
from app.viewer3d.fallback_viewer import FallbackMeshViewer
from app.workers.process_runner import ProcessRunner
from app.workers.freecad_worker import FreeCADJob, FreeCADWorker
from app.workers.rag_worker import RagWorker
from app.workers.viewer_worker import ViewerWorker, ViewerWorkerResult


class FunctionWorker(QObject):
    finished = Signal(object)
    failed = Signal(str)
    progress = Signal(str)

    def __init__(self, func: Callable[..., Any], *args: Any, emit_progress: bool = False, **kwargs: Any) -> None:
        super().__init__()
        self.func = func
        self.args = args
        self.kwargs = kwargs
        self.emit_progress = emit_progress

    def run(self) -> None:
        try:
            kwargs = dict(self.kwargs)
            if self.emit_progress:
                params = inspect.signature(self.func).parameters
                if "on_status" in params and "on_status" not in kwargs:
                    kwargs["on_status"] = lambda message: self.progress.emit(str(message))
                if "on_line" in params and "on_line" not in kwargs:
                    kwargs["on_line"] = self._line_progress
            self.finished.emit(self.func(*self.args, **kwargs))
        except Exception:
            self.failed.emit(traceback.format_exc())

    def _line_progress(self, stream: str, line: str) -> None:
        text = line.rstrip()
        if text:
            self.progress.emit(f"{stream}: {text}")


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("FreeCAD Prompt Forge")
        self.resize(1320, 840)
        self.rag = LocalRagStore()
        self.agent = PromptAgent(self.rag)
        self.current_design: GeneratedDesign | None = None
        self.last_run_result: RunResult | None = None
        self.current_job_result: CadJobResult | None = None
        self._threads: list[QThread] = []
        self._workers: list[FunctionWorker] = []

        mono = QFont("DejaVu Sans Mono")
        mono.setStyleHint(QFont.Monospace)
        mono.setPointSize(10)

        self.prompt_edit = QPlainTextEdit()
        self.prompt_edit.setObjectName("PromptInput")
        self.prompt_edit.setPlaceholderText(
            "Crie uma placa de aluminio 120x80x6 mm com quatro furos de 6 mm nos cantos e um rasgo central de 40x12 mm."
        )
        self.prompt_edit.setMinimumHeight(150)
        self.auto_correct_check = QCheckBox("Corrigir ambiguidades automaticamente")
        self.auto_correct_check.setChecked(True)

        self.output_dir_edit = QLineEdit(str(OUTPUT_DIR))
        self.freecad_label = QLabel(self._freecad_status())
        self.rag_label = QLabel(self._rag_status())
        self.viewer_mode_label = QLabel("mesh_fallback")
        self.macro_dir_label = QLabel(str(MACROS_DIR))

        self.generate_button = self._button("Gerar Macro", QStyle.SP_FileDialogNewFolder)
        self.run_button = self._button("Executar Headless", QStyle.SP_MediaPlay)
        self.generate_export_button = self._button("Gerar e Exportar", QStyle.SP_DialogApplyButton)
        self.generate_view_button = self._button("Gerar, Executar e Visualizar", QStyle.SP_ComputerIcon)
        self.cancel_button = self._button("Cancelar Execucao", QStyle.SP_BrowserStop)
        self.test_freecad_button = self._button("Testar FreeCAD", QStyle.SP_DialogApplyButton)
        self.rebuild_rag_button = self._button("Reconstruir RAG", QStyle.SP_BrowserReload)
        self.open_output_button = self._button("Abrir Saida", QStyle.SP_DirOpenIcon)
        self.open_job_button = self._button("Abrir Pasta do Job", QStyle.SP_DirOpenIcon)
        self.open_part_button = self._button("Abrir Peca no FreeCAD", QStyle.SP_ComputerIcon)
        self.reload_viewer_button = self._button("Recarregar Viewer", QStyle.SP_BrowserReload)
        self.open_stl_button = self._button("Abrir STL Externo", QStyle.SP_FileDialogDetailedView)
        self.open_step_button = self._button("Abrir STEP Externo", QStyle.SP_FileDialogDetailedView)
        self.copy_error_button = self._button("Copiar Erro", QStyle.SP_FileIcon)
        self.clear_visual_cache_button = self._button("Limpar Cache Visual", QStyle.SP_TrashIcon)
        self.reset_app_button = self._button("Resetar Aplicacao", QStyle.SP_DialogResetButton)
        self.view_logs_button = self._button("Ver Logs", QStyle.SP_FileDialogContentsView)
        self.diagnostic_package_button = self._button("Gerar Diagnostico", QStyle.SP_MessageBoxInformation)
        self.choose_output_button = self._button("", QStyle.SP_DirOpenIcon)
        self.search_button = self._button("Buscar", QStyle.SP_FileDialogContentsView)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Buscar na base local de FreeCAD")

        self.result_view = QPlainTextEdit()
        self.result_view.setReadOnly(True)

        self.macro_view = QPlainTextEdit()
        self.macro_view.setFont(mono)

        self.rag_view = QPlainTextEdit()
        self.rag_view.setReadOnly(True)

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setFont(mono)

        self.activity_label = QLabel("Pronto")
        self.activity_label.setObjectName("ActivityLabel")
        self.activity_progress = QProgressBar()
        self.activity_progress.setRange(0, 1)
        self.activity_progress.setValue(1)
        self.activity_progress.setTextVisible(False)
        self.activity_log = QPlainTextEdit()
        self.activity_log.setObjectName("ActivityLog")
        self.activity_log.setReadOnly(True)
        self.activity_log.setMaximumHeight(118)
        self.activity_log.setFont(mono)

        self.execution_view = QPlainTextEdit()
        self.execution_view.setReadOnly(True)
        self.execution_view.setFont(mono)

        self.export_view = QPlainTextEdit()
        self.export_view.setReadOnly(True)

        self.diagnostic_view = QPlainTextEdit()
        self.diagnostic_view.setReadOnly(True)
        self.diagnostic_view.setFont(mono)

        self.library_view = QPlainTextEdit()
        self.library_view.setReadOnly(True)

        self.settings_view = QPlainTextEdit()
        self.settings_view.setReadOnly(True)

        self.viewer = FallbackMeshViewer()
        self.viewer_status_label = QLabel("Nenhuma malha carregada")
        self.viewer_dimensions_label = QLabel("Dimensoes: -")
        self.viewer_measure_label = QLabel("Medida: -")
        self.object_tree = QTreeWidget()
        self.object_tree.setHeaderLabels(["Objeto", "Valor"])

        self.import_path_edit = QLineEdit()
        self.import_path_edit.setPlaceholderText("Arquivo DXF, DWG ou SVG")
        self.import_type_combo = QComboBox()
        self.import_type_combo.addItems(["auto", "dxf", "dwg", "svg", "step", "stl", "obj", "brep"])
        self.unit_combo = QComboBox()
        self.unit_combo.addItems(["mm", "cm", "m", "in"])
        self.scale_spin = QDoubleSpinBox()
        self.scale_spin.setRange(0.001, 1000.0)
        self.scale_spin.setDecimals(4)
        self.scale_spin.setValue(1.0)
        self.thickness_spin = QDoubleSpinBox()
        self.thickness_spin.setRange(0.1, 1000.0)
        self.thickness_spin.setDecimals(2)
        self.thickness_spin.setValue(2.0)
        self.center_check = QCheckBox("Centralizar")
        self.center_check.setChecked(True)
        self.clean_check = QCheckBox("Limpar geometria")
        self.clean_check.setChecked(True)
        self.extrude_check = QCheckBox("Extrudar para 3D")
        self.extrude_check.setChecked(True)
        self.import_report_view = QPlainTextEdit()
        self.import_report_view.setReadOnly(True)
        self.import_select_button = self._button("Selecionar", QStyle.SP_DialogOpenButton)
        self.import_run_button = self._button("Importar CAD", QStyle.SP_DialogApplyButton)

        self.doctor_button = self._button("Rodar Doctor", QStyle.SP_MessageBoxInformation)

        self._build_layout()
        self._connect()
        self._toolbar()
        self._refresh_library()
        self._refresh_settings()
        self._set_busy(False, "Pronto")

    def _button(self, text: str, icon: QStyle.StandardPixmap) -> QPushButton:
        button = QPushButton(text)
        button.setIcon(self.style().standardIcon(icon))
        button.setMinimumHeight(34)
        return button

    def _build_layout(self) -> None:
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(14, 14, 14, 14)
        left_layout.setSpacing(10)

        prompt_label = QLabel("Prompt CAD")
        prompt_label.setObjectName("PanelTitle")
        left_layout.addWidget(prompt_label)
        left_layout.addWidget(self.prompt_edit)
        left_layout.addWidget(self.auto_correct_check)
        left_layout.addWidget(self.generate_button)
        left_layout.addWidget(self.run_button)
        left_layout.addWidget(self.generate_export_button)
        left_layout.addWidget(self.generate_view_button)
        left_layout.addWidget(self.cancel_button)
        left_layout.addWidget(self.test_freecad_button)

        activity_group = QGroupBox("Atividade")
        activity_layout = QVBoxLayout(activity_group)
        activity_layout.addWidget(self.activity_label)
        activity_layout.addWidget(self.activity_progress)
        activity_layout.addWidget(self.activity_log)
        left_layout.addWidget(activity_group)

        form = QFormLayout()
        output_row = QHBoxLayout()
        output_row.addWidget(self.output_dir_edit)
        output_row.addWidget(self.choose_output_button)
        form.addRow("Saida", output_row)
        form.addRow("Macros", self.macro_dir_label)
        form.addRow("FreeCAD", self.freecad_label)
        form.addRow("RAG", self.rag_label)
        form.addRow("Viewer", self.viewer_mode_label)
        left_layout.addLayout(form)
        left_layout.addWidget(self.open_output_button)
        left_layout.addWidget(self.open_job_button)
        left_layout.addWidget(self.open_part_button)
        viewer_actions = QHBoxLayout()
        viewer_actions.addWidget(self.reload_viewer_button)
        viewer_actions.addWidget(self.clear_visual_cache_button)
        left_layout.addLayout(viewer_actions)
        external_actions = QHBoxLayout()
        external_actions.addWidget(self.open_stl_button)
        external_actions.addWidget(self.open_step_button)
        left_layout.addLayout(external_actions)
        diag_actions = QHBoxLayout()
        diag_actions.addWidget(self.copy_error_button)
        diag_actions.addWidget(self.view_logs_button)
        left_layout.addLayout(diag_actions)
        left_layout.addWidget(self.diagnostic_package_button)
        left_layout.addWidget(self.reset_app_button)

        base_label = QLabel("Conhecimento")
        base_label.setObjectName("PanelTitle")
        left_layout.addWidget(base_label)
        left_layout.addWidget(self.search_edit)
        search_row = QHBoxLayout()
        search_row.addWidget(self.search_button)
        search_row.addWidget(self.rebuild_rag_button)
        left_layout.addLayout(search_row)
        left_layout.addStretch(1)

        self.tabs = QTabWidget()
        self.tabs.addTab(self.result_view, "Prompt CAD")
        self.tabs.addTab(self._viewer_tab(), "Visualizacao 3D")
        self.tabs.addTab(self._import_tab(), "Importar CAD")
        self.tabs.addTab(self.library_view, "Biblioteca")
        self.tabs.addTab(self.rag_view, "RAG")
        self.tabs.addTab(self.macro_view, "Macro")
        self.tabs.addTab(self.execution_view, "Execucao")
        self.tabs.addTab(self.export_view, "Exportacao")
        self.tabs.addTab(self._diagnostic_tab(), "Diagnostico Visual")
        self.tabs.addTab(self.settings_view, "Configuracoes")
        self.tabs.addTab(self.log_view, "Logs")
        self.tabs.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        splitter = QSplitter()
        splitter.addWidget(left)
        splitter.addWidget(self.tabs)
        splitter.setSizes([390, 930])
        self.setCentralWidget(splitter)

    def _viewer_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(10, 10, 10, 10)

        controls = QHBoxLayout()
        for label, callback in (
            ("Iso", lambda: self.viewer.set_view("isometric")),
            ("Frente", lambda: self.viewer.set_view("front")),
            ("Topo", lambda: self.viewer.set_view("top")),
            ("Lateral", lambda: self.viewer.set_view("side")),
            ("Zoom", self.viewer.zoom_extents),
            ("Reset", self.viewer.reset_view),
        ):
            button = QPushButton(label)
            button.clicked.connect(callback)
            controls.addWidget(button)

        display_combo = QComboBox()
        display_combo.addItems(["shaded", "shaded_with_edges", "wireframe"])
        display_combo.currentTextChanged.connect(self.viewer.set_display_mode)
        controls.addWidget(display_combo)

        axes_check = QCheckBox("Eixos")
        axes_check.setChecked(False)
        axes_check.toggled.connect(self._toggle_axes)
        controls.addWidget(axes_check)

        bbox_check = QCheckBox("BBox")
        bbox_check.setChecked(False)
        bbox_check.toggled.connect(self._toggle_bbox)
        controls.addWidget(bbox_check)

        material_button = QPushButton("Cor Peca")
        material_button.clicked.connect(self._choose_material_color)
        controls.addWidget(material_button)

        bg_button = QPushButton("Cor Fundo")
        bg_button.clicked.connect(self._choose_background_color)
        controls.addWidget(bg_button)

        screenshot_button = QPushButton("PNG")
        screenshot_button.clicked.connect(self.export_viewer_png)
        controls.addWidget(screenshot_button)

        transparency = QSlider(Qt.Horizontal)
        transparency.setRange(20, 255)
        transparency.setValue(245)
        transparency.setFixedWidth(110)
        transparency.valueChanged.connect(self._set_viewer_alpha)
        controls.addWidget(QLabel("Alpha"))
        controls.addWidget(transparency)
        controls.addStretch(1)

        body = QSplitter()
        body.addWidget(self.viewer)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.addWidget(self.viewer_status_label)
        right_layout.addWidget(self.viewer_dimensions_label)
        right_layout.addWidget(self.viewer_measure_label)
        right_layout.addWidget(self.object_tree)
        body.addWidget(right)
        body.setSizes([720, 260])

        layout.addLayout(controls)
        layout.addWidget(body)
        return tab

    def _import_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(12, 12, 12, 12)

        form_group = QGroupBox("Arquivo CAD")
        form = QFormLayout(form_group)
        file_row = QHBoxLayout()
        file_row.addWidget(self.import_path_edit)
        file_row.addWidget(self.import_select_button)
        form.addRow("Arquivo", file_row)
        form.addRow("Tipo", self.import_type_combo)
        form.addRow("Unidade", self.unit_combo)
        form.addRow("Escala", self.scale_spin)
        form.addRow("Espessura", self.thickness_spin)
        toggles = QHBoxLayout()
        toggles.addWidget(self.center_check)
        toggles.addWidget(self.clean_check)
        toggles.addWidget(self.extrude_check)
        form.addRow("Opcoes", toggles)
        form.addRow("", self.import_run_button)

        layout.addWidget(form_group)
        layout.addWidget(self.import_report_view)
        return tab

    def _diagnostic_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.addWidget(self.doctor_button)
        layout.addWidget(self.diagnostic_view)
        return tab

    def _toolbar(self) -> None:
        toolbar = QToolBar("Acoes")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)
        actions = [
            ("Gerar", QStyle.SP_FileDialogNewFolder, self.generate_macro),
            ("Executar", QStyle.SP_MediaPlay, self.run_current_macro),
            ("Visualizar", QStyle.SP_ComputerIcon, self.generate_execute_visualize),
            ("Abrir Peca", QStyle.SP_ComputerIcon, self.open_latest_part),
            ("Abrir Saida", QStyle.SP_DirOpenIcon, self.open_output_dir),
        ]
        for label, icon, callback in actions:
            action = QAction(self.style().standardIcon(icon), label, self)
            action.triggered.connect(callback)
            toolbar.addAction(action)

    def _connect(self) -> None:
        self.generate_button.clicked.connect(self.generate_macro)
        self.run_button.clicked.connect(self.run_current_macro)
        self.generate_export_button.clicked.connect(self.generate_and_export)
        self.generate_view_button.clicked.connect(self.generate_execute_visualize)
        self.cancel_button.clicked.connect(self.cancel_execution)
        self.test_freecad_button.clicked.connect(self.test_freecad_ui)
        self.rebuild_rag_button.clicked.connect(self.rebuild_rag)
        self.open_output_button.clicked.connect(self.open_output_dir)
        self.open_job_button.clicked.connect(self.open_job_dir)
        self.open_part_button.clicked.connect(self.open_latest_part)
        self.reload_viewer_button.clicked.connect(self.reload_viewer)
        self.open_stl_button.clicked.connect(lambda: self.open_external("STL"))
        self.open_step_button.clicked.connect(lambda: self.open_external("STEP"))
        self.copy_error_button.clicked.connect(self.copy_last_error)
        self.clear_visual_cache_button.clicked.connect(self.clear_visual_cache)
        self.reset_app_button.clicked.connect(self.reset_application)
        self.view_logs_button.clicked.connect(self.view_logs)
        self.diagnostic_package_button.clicked.connect(self.generate_diagnostic_package)
        self.choose_output_button.clicked.connect(self.choose_output_dir)
        self.search_button.clicked.connect(self.search_rag)
        self.search_edit.returnPressed.connect(self.search_rag)
        self.import_select_button.clicked.connect(self.select_import_file)
        self.import_run_button.clicked.connect(self.import_cad)
        self.doctor_button.clicked.connect(self.run_doctor_ui)

    def _freecad_status(self) -> str:
        return find_freecad_executable() or "nao encontrado"

    def _rag_status(self) -> str:
        chunks_path = RAG_DIR / "chunks_v2.json"
        if chunks_path.exists():
            try:
                return f"{len(json.loads(chunks_path.read_text(encoding='utf-8')))} chunks"
            except Exception:
                pass
        return f"{len(self.rag.chunks)} chunks" if self.rag.chunks else "sem indice"

    def choose_output_dir(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "Selecionar pasta de saida", self.output_dir_edit.text())
        if directory:
            self.output_dir_edit.setText(directory)
            self.agent = PromptAgent(
                self.rag,
                output_dir=Path(directory).expanduser(),
                auto_correct_geometry=self.auto_correct_check.isChecked(),
            )
            self._refresh_settings()

    def open_output_dir(self) -> None:
        output_dir = Path(self.output_dir_edit.text()).expanduser()
        output_dir.mkdir(parents=True, exist_ok=True)
        self._activity(f"Abrindo pasta de saida: {output_dir}")
        subprocess.Popen(["xdg-open", str(output_dir)])

    def open_job_dir(self) -> None:
        directory = self.current_job_result.job_dir if self.current_job_result else None
        if directory is None:
            files = sorted((OUTPUT_DIR / "jobs").glob("*"), key=lambda path: path.stat().st_mtime, reverse=True)
            directory = files[0] if files else OUTPUT_DIR
        self._activity(f"Abrindo pasta do job: {directory}")
        subprocess.Popen(["xdg-open", str(directory)])

    def cancel_execution(self) -> None:
        count = ProcessRunner.cancel_all()
        self._set_busy(False, "Cancelamento solicitado")
        self._activity(f"Processos cancelados: {count}")
        for line in ProcessRunner.last_cancel_report_lines():
            self._activity(f"Cancelamento: {line}")
        if count == 0:
            self._activity("Falha no cancelamento: nenhum processo rastreado pelo ProcessRunner.")

    def test_freecad_ui(self) -> None:
        self._set_busy(True, "Rodando teste minimo FreeCAD...")
        self._activity("Teste minimo: cilindro simples -> FCStd, STEP e STL.")
        self._start_worker(
            FreeCADWorker().run_minimal_test,
            self._handle_freecad_test_result,
            True,
            with_progress=True,
        )

    def _handle_freecad_test_result(self, result: object) -> None:
        self._set_busy(False, result.message if hasattr(result, "message") else "Teste FreeCAD concluido")
        payload = result.to_json_dict() if hasattr(result, "to_json_dict") else result
        self.execution_view.setPlainText(json.dumps(payload, ensure_ascii=False, indent=2))
        if hasattr(result, "success") and result.success:
            self._activity(f"FreeCAD OK em {result.elapsed_sec:.2f}s; FCStd/STEP/STL gerados.")
        else:
            self._activity("Teste minimo FreeCAD falhou. Veja aba Execucao.")
        self.tabs.setCurrentWidget(self.execution_view)

    def reload_viewer(self) -> None:
        if self.last_run_result:
            self._load_result_in_viewer(self.last_run_result)
        elif self.current_job_result and self.current_job_result.freecad:
            self._load_result_in_viewer(self.current_job_result.freecad)
        else:
            self._activity("Nenhum resultado CAD para recarregar no viewer.")

    def open_external(self, kind: str) -> None:
        path = None
        if self.current_job_result and self.current_job_result.freecad:
            path = self.current_job_result.freecad.output_paths.get(kind)
        elif self.last_run_result:
            path = self.last_run_result.output_paths.get(kind)
        if not path:
            QMessageBox.warning(self, f"Abrir {kind}", f"Nenhum arquivo {kind} encontrado.")
            return
        subprocess.Popen(["xdg-open", str(path)])

    def copy_last_error(self) -> None:
        text = ""
        if self.current_job_result and self.current_job_result.freecad and not self.current_job_result.freecad.success:
            text = "\n".join(
                [
                    self.current_job_result.freecad.message,
                    self.current_job_result.freecad.stderr,
                    self.current_job_result.freecad.stdout,
                ]
            )
        else:
            text = self.execution_view.toPlainText()[-4000:]
        QApplication.clipboard().setText(text)
        self._activity("Erro/execucao copiado para a area de transferencia.")

    def clear_visual_cache(self) -> None:
        self.viewer.scene().clear()
        self.object_tree.clear()
        self.viewer_status_label.setText("Viewer limpo")
        self._activity("Cache visual limpo.")

    def reset_application(self) -> None:
        self.current_design = None
        self.last_run_result = None
        self.current_job_result = None
        for widget in (self.result_view, self.macro_view, self.execution_view, self.export_view):
            widget.clear()
        self.clear_visual_cache()
        self._set_busy(False, "Aplicacao resetada")

    def view_logs(self) -> None:
        self.tabs.setCurrentWidget(self.log_view)

    def generate_diagnostic_package(self) -> None:
        freecad_payload = None
        job_dir = None
        if self.current_job_result:
            job_dir = self.current_job_result.job_dir
            if self.current_job_result.freecad:
                freecad_payload = self.current_job_result.freecad.to_json_dict()
        zip_path = create_failure_package(self.current_design, job_dir=job_dir, freecad_payload=freecad_payload)
        self._activity(f"Pacote de diagnostico gerado: {zip_path}")
        self.diagnostic_view.setPlainText(f"Pacote de diagnostico:\n{zip_path}")
        self.tabs.setCurrentWidget(self.diagnostic_view)

    def open_latest_part(self) -> None:
        fcstd: Path | None = None
        if self.current_job_result and self.current_job_result.freecad:
            fcstd = self.current_job_result.freecad.output_paths.get("FCStd")
        elif self.last_run_result:
            fcstd = self.last_run_result.output_paths.get("FCStd")
        if fcstd is None:
            files = sorted(OUTPUT_DIR.glob("**/*.FCStd"), key=lambda path: path.stat().st_mtime, reverse=True)
            fcstd = files[0] if files else None
        if fcstd is None or not fcstd.exists():
            QMessageBox.warning(self, "Abrir peca", "Nenhum arquivo .FCStd encontrado para abrir.")
            return
        freecad = find_freecad_executable()
        if not freecad:
            QMessageBox.warning(self, "Abrir peca", "FreeCAD nao foi encontrado.")
            return
        self._activity(f"Abrindo peca no FreeCAD: {fcstd.name}")
        log_path = Path(self.output_dir_edit.text()).expanduser().parent / "logs" / "opened_freecad.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("ab") as log_handle:
            subprocess.Popen([freecad, str(fcstd)], stdout=log_handle, stderr=subprocess.STDOUT)

    def generate_macro(self, keep_busy: bool = False) -> GeneratedDesign | None:
        prompt = self.prompt_edit.toPlainText().strip()
        if not prompt:
            QMessageBox.information(self, "Prompt vazio", "Digite uma descricao da peca.")
            return None
        self._set_busy(True, "Preparando geracao da macro...")
        try:
            output_dir = Path(self.output_dir_edit.text()).expanduser()
            output_dir.mkdir(parents=True, exist_ok=True)
            self.agent = PromptAgent(
                self.rag,
                output_dir=output_dir,
                auto_correct_geometry=self.auto_correct_check.isChecked(),
            )
            self._activity("Consultando RAG local para contexto tecnico...")
            self._activity("Chamando DeepSeek para auxiliar a macro; fallback local fica armado se a API falhar...")
            design = self.agent.generate(prompt)
        except Exception as exc:
            self._set_busy(False, "Erro ao gerar macro")
            QMessageBox.critical(self, "Erro ao gerar macro", str(exc))
            self.log_view.appendPlainText(traceback.format_exc())
            return None
        self.current_design = design
        self.macro_view.setPlainText(design.macro_code)
        self.result_view.setPlainText(self._format_result(design))
        self.rag_view.setPlainText(self.rag.format_results(list(design.rag_results)))
        deepseek_status = "DeepSeek usado" if design.llm_used else "DeepSeek nao usado; fallback local aplicado"
        self._activity(f"Macro gerada: {design.macro_path.name} ({deepseek_status})")
        self._refresh_export_view()
        if not keep_busy:
            self._set_busy(False, "Macro pronta")
            self.tabs.setCurrentWidget(self.macro_view)
        return design

    def run_current_macro(self) -> None:
        prompt = self.prompt_edit.toPlainText().strip() or (self.current_design.prompt if self.current_design else "")
        if not prompt:
            QMessageBox.information(self, "Prompt vazio", "Digite uma descricao da peca.")
            return
        self._set_busy(True, "Job: executando e visualizando")
        self._activity("Executar: usando pipeline de job completo para gerar FCStd/STEP/STL e carregar viewer.")
        manager = JobManager(self.rag, auto_correct_geometry=self.auto_correct_check.isChecked())
        self._start_worker(
            manager.run_prompt,
            self._handle_job_result,
            prompt,
            True,
            90,
            with_progress=True,
        )

    def generate_and_export(self) -> None:
        self._activity("Fluxo iniciado: gerar macro e exportar CAD.")
        self.generate_execute_visualize()

    def generate_execute_visualize(self) -> None:
        prompt = self.prompt_edit.toPlainText().strip()
        if not prompt:
            QMessageBox.information(self, "Prompt vazio", "Digite uma descricao da peca.")
            return
        self._set_busy(True, "Job: gerando macro")
        self._activity("Pipeline: interpretar prompt -> gerar macro -> executar FreeCAD headless -> carregar viewer.")
        manager = JobManager(self.rag, auto_correct_geometry=self.auto_correct_check.isChecked())
        self._start_worker(
            manager.run_prompt,
            self._handle_job_result,
            prompt,
            True,
            120,
            with_progress=True,
        )

    def _handle_job_result(self, result: CadJobResult) -> None:
        self.current_job_result = result
        self.current_design = result.design
        self.macro_view.setPlainText(result.design.macro_code)
        self.result_view.setPlainText(self._format_result(result.design, result.freecad))
        self.rag_view.setPlainText(self.rag.format_results(list(result.design.rag_results)))
        self._set_busy(False, result.freecad.message if result.freecad else "Macro gerada")
        self._activity(f"Job finalizado em {result.elapsed_sec:.2f}s: {result.job_dir}")
        if result.freecad:
            self.execution_view.setPlainText(json.dumps(result.freecad.to_json_dict(), ensure_ascii=False, indent=2))
            self._update_visual_diagnostics(result)
            if result.freecad.success:
                self._activity("Arquivos CAD confirmados. Preparando viewer em worker...")
                self._load_result_in_viewer(result.freecad)
            else:
                self._activity(f"Erro FreeCAD: {result.freecad.error_type} - {result.freecad.message}")
                self.tabs.setCurrentWidget(self.execution_view)
                QMessageBox.warning(self, "FreeCAD", result.freecad.message)
        self._refresh_export_view()
        self._refresh_library()

    def _update_visual_diagnostics(self, result: CadJobResult) -> None:
        freecad = result.freecad
        lines = [
            f"Job: {result.job_id}",
            f"Prompt: {result.prompt}",
            f"Macro: {result.design.macro_path}",
            f"Pasta do job: {result.job_dir}",
            f"Tempo total: {result.elapsed_sec:.2f}s",
        ]
        if freecad:
            lines.extend(
                [
                    f"Sucesso: {freecad.success}",
                    f"Modo executor: {freecad.mode}",
                    f"Tempo FreeCAD: {freecad.elapsed_sec:.2f}s",
                    f"Erro: {freecad.error_type or '-'}",
                    f"Mensagem: {freecad.message}",
                    f"Log bruto: {freecad.log_file or '-'}",
                ]
            )
            for key in ("FCStd", "STEP", "STL", "OBJ", "BREP", "metadata", "build_report"):
                path = freecad.output_paths.get(key)
                size = path.stat().st_size if path and path.exists() else 0
                lines.append(f"{key}: {path or '-'} ({size} bytes)")
            if not freecad.success:
                lines.extend(["", "STDERR:", freecad.stderr[-4000:], "", "STDOUT:", freecad.stdout[-4000:]])
        self.diagnostic_view.setPlainText("\n".join(lines))

    def _handle_run_result(self, result: RunResult) -> None:
        self.last_run_result = result if isinstance(result, RunResult) else None
        self._set_busy(False, result.message)
        outputs = "\n".join(f"{kind}: {path}" for kind, path in result.output_paths.items()) or "(nenhum)"
        ok = result.success if hasattr(result, "success") else result.ok
        execution_text = "\n".join(
            [
                f"Modo: {result.mode}",
                f"Comando: {' '.join(result.command) if result.command else '(nenhum)'}",
                f"Status: {result.message}",
                f"Return code: {result.returncode}",
                f"Arquivos:\n{outputs}",
                "",
                "STDOUT:",
                result.stdout,
                "STDERR:",
                result.stderr,
            ]
        )
        self.execution_view.setPlainText(execution_text)
        self.log_view.appendPlainText("\n" + execution_text)
        if self.current_design:
            self.result_view.setPlainText(self._format_result(self.current_design, result))
        if ok:
            self._activity("FreeCAD executou a macro e confirmou arquivos. Carregando STL/OBJ no viewer...")
            self._load_result_in_viewer(result)
        else:
            self._activity("FreeCAD terminou sem gerar os arquivos esperados. Veja a aba Execucao.")
            self.tabs.setCurrentWidget(self.execution_view)
            QMessageBox.warning(self, "FreeCAD", result.message)
        self._refresh_export_view()
        self._refresh_library()

    def rebuild_rag(self) -> None:
        self._set_busy(True, "Reconstruindo RAG v2...")
        self._activity("Iniciando ingestao RAG v2.")
        self._start_worker(RagWorker().rebuild, self._handle_rag_rebuilt, with_progress=True)

    def _handle_rag_rebuilt(self, audit: object) -> None:
        self.rag.reload()
        self.agent = PromptAgent(
            self.rag,
            output_dir=Path(self.output_dir_edit.text()).expanduser(),
            auto_correct_geometry=self.auto_correct_check.isChecked(),
        )
        self.rag_label.setText(self._rag_status())
        self._set_busy(False, "RAG reconstruido")
        payload = audit.audit if hasattr(audit, "audit") else audit
        self.rag_view.setPlainText(json.dumps(payload, ensure_ascii=False, indent=2))
        self._activity(f"RAG v2 pronto: {self._rag_status()}.")
        self._refresh_settings()

    def search_rag(self) -> None:
        query = self.search_edit.text().strip() or self.prompt_edit.toPlainText().strip()
        if not query:
            QMessageBox.information(self, "Busca vazia", "Digite uma busca ou um prompt.")
            return
        results = self.rag.search(query, limit=8)
        self.rag_view.setPlainText(self.rag.format_results(results))
        self._activity(f"Busca RAG concluida: {len(results)} resultados.")
        self.tabs.setCurrentWidget(self.rag_view)

    def select_import_file(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Selecionar CAD",
            str(Path.home()),
            "CAD (*.dxf *.dwg *.svg *.step *.stp *.stl *.obj *.brep *.brp);;DXF (*.dxf);;DWG (*.dwg);;SVG (*.svg);;STEP/BREP (*.step *.stp *.brep *.brp);;Mesh (*.stl *.obj);;Todos (*.*)",
        )
        if filename:
            self.import_path_edit.setText(filename)
            suffix = Path(filename).suffix.lower().lstrip(".")
            if suffix in {"dxf", "dwg", "svg", "step", "stp", "stl", "obj", "brep", "brp"}:
                self.import_type_combo.setCurrentText("step" if suffix in {"stp", "brp"} else suffix)

    def import_cad(self) -> None:
        path = Path(self.import_path_edit.text()).expanduser()
        if not path.exists():
            QMessageBox.warning(self, "Importar CAD", "Arquivo nao encontrado.")
            return
        self._set_busy(True, "Importando CAD...")
        self._activity(f"Importando arquivo CAD: {path.name}")
        self._start_worker(self._import_file, self._handle_import_result, path)

    def _import_file(self, path: Path) -> ImportReport:
        import_type = self.import_type_combo.currentText()
        if import_type == "auto":
            import_type = path.suffix.lower().lstrip(".")
        unit_factor = {"mm": 1.0, "cm": 10.0, "m": 1000.0, "in": 25.4}[self.unit_combo.currentText()]
        scale = float(self.scale_spin.value()) * unit_factor
        thickness = float(self.thickness_spin.value())
        output_dir = Path(self.output_dir_edit.text()).expanduser()
        if import_type == "dxf":
            return DxfImporter(output_dir).import_file(
                path,
                unit=self.unit_combo.currentText(),
                scale=scale,
                extrude=self.extrude_check.isChecked(),
                thickness=thickness,
                center=self.center_check.isChecked(),
            )
        if import_type == "svg":
            return SvgImporter(output_dir).import_file(
                path,
                scale=scale,
                extrude=self.extrude_check.isChecked(),
                thickness=thickness,
                center=self.center_check.isChecked(),
            )
        if import_type == "dwg":
            return DwgImporter(output_dir).import_file(path)
        if import_type in {"step", "brep"} or path.suffix.lower() in {".step", ".stp", ".brep", ".brp"}:
            return StepImporter(output_dir).import_file(path)
        if import_type in {"stl", "obj"} or path.suffix.lower() in {".stl", ".obj"}:
            return MeshImporter(output_dir).import_file(path)
        return ImportReport(False, import_type, str(path), f"Formato nao suportado: {import_type}")

    def _handle_import_result(self, report: ImportReport) -> None:
        self._set_busy(False, report.message)
        text = report.to_markdown()
        self.import_report_view.setPlainText(text)
        self._activity(f"Importacao {report.importer}: {report.message}")
        self._refresh_export_view()
        if report.output_paths:
            fake_result = RunResult(
                ok=report.ok,
                command=(),
                returncode=0 if report.ok else 1,
                stdout=text,
                stderr="",
                message=report.message,
                mode=f"import_{report.importer}",
                output_paths={key: Path(value) for key, value in report.output_paths.items()},
            )
            self._load_result_in_viewer(fake_result)
        if not report.ok:
            QMessageBox.warning(self, "Importar CAD", report.message)

    def run_doctor_ui(self) -> None:
        self._set_busy(True, "Rodando doctor...")
        self._activity("Rodando doctor: Python, FreeCAD, RAG, viewer, importadores e UI...")
        self._start_worker(run_doctor, self._handle_doctor_result)

    def _handle_doctor_result(self, payload: dict[str, object]) -> None:
        self._set_busy(False, "Doctor concluido")
        self.diagnostic_view.setPlainText(json.dumps(payload, ensure_ascii=False, indent=2))
        self._activity(f"Doctor concluido: {DIAGNOSTICS_DIR / 'doctor_report.md'}")
        self.tabs.setCurrentWidget(self.diagnostic_view)

    def _load_result_in_viewer(self, result: RunResult) -> None:
        mesh_path = result.output_paths.get("STL") or result.output_paths.get("OBJ")
        if not mesh_path:
            self.viewer_status_label.setText("Sem STL/OBJ para visualizacao")
            return
        self._set_busy(True, "Job: carregando viewer")
        output_dir = self.current_job_result.job_dir if self.current_job_result else Path(mesh_path).parent
        self._start_worker(ViewerWorker().prepare, self._handle_viewer_prepared, Path(mesh_path), output_dir)

    def _handle_viewer_prepared(self, result: ViewerWorkerResult) -> None:
        self._set_busy(False, result.message)
        self.viewer_mode_label.setText(result.viewer_mode)
        self.viewer_status_label.setText(result.message)
        if result.ok and result.vertices is not None and result.faces is not None:
            status = self.viewer.set_mesh_data(result.vertices, result.faces, result.mesh_path)
            self.viewer_status_label.setText(status.message)
            if result.mesh_path:
                self._update_viewer_metadata(Path(result.mesh_path))
            self._activity(f"Peca carregada no viewer ({result.viewer_mode}).")
            self.tabs.setCurrentIndex(1)
        elif result.preview_images:
            self._activity("Viewer 3D indisponivel; previews PNG foram gerados no job.")
            self.export_view.setPlainText("\n".join(str(path) for path in result.preview_images.values()))
            self.tabs.setCurrentWidget(self.export_view)
        else:
            self._activity(f"Arquivo STL/OBJ gerado, mas falhou ao carregar no viewer. {result.error}")

    def _update_viewer_metadata(self, mesh_path: Path) -> None:
        self.object_tree.clear()
        self.object_tree.addTopLevelItem(QTreeWidgetItem(["Arquivo", str(mesh_path)]))
        if self.viewer.vertices is None or self.viewer.faces is None:
            return
        import numpy as np

        vertices = self.viewer.vertices
        faces = self.viewer.faces
        mins = vertices.min(axis=0)
        maxs = vertices.max(axis=0)
        lengths = maxs - mins
        diagonal = float(np.linalg.norm(lengths))
        self.viewer_dimensions_label.setText(f"Dimensoes: X={lengths[0]:.3f} Y={lengths[1]:.3f} Z={lengths[2]:.3f}")
        self.viewer_measure_label.setText(f"Medida: diagonal BBox={diagonal:.3f}")
        for key, value in (
            ("Vertices", len(vertices)),
            ("Faces", len(faces)),
            ("X", f"{lengths[0]:.3f}"),
            ("Y", f"{lengths[1]:.3f}"),
            ("Z", f"{lengths[2]:.3f}"),
        ):
            self.object_tree.addTopLevelItem(QTreeWidgetItem([str(key), str(value)]))
        self.object_tree.expandAll()

    def _toggle_axes(self, checked: bool) -> None:
        self.viewer.show_axes = checked
        self.viewer.render_scene()

    def _toggle_bbox(self, checked: bool) -> None:
        self.viewer.show_bbox = checked
        self.viewer.render_scene()

    def _set_viewer_alpha(self, value: int) -> None:
        if hasattr(self.viewer, "set_transparency"):
            self.viewer.set_transparency(value)

    def _choose_material_color(self) -> None:
        color = QColorDialog.getColor(QColor("#c0cad6"), self, "Cor da peca")
        if color.isValid() and hasattr(self.viewer, "set_material_color"):
            self.viewer.set_material_color(color)

    def _choose_background_color(self) -> None:
        color = QColorDialog.getColor(QColor("#ffffff"), self, "Cor do fundo")
        if color.isValid() and hasattr(self.viewer, "set_background_color"):
            self.viewer.set_background_color(color)

    def export_viewer_png(self) -> None:
        target = Path(self.output_dir_edit.text()).expanduser() / "viewer_screenshot.png"
        self.viewer.export_png(target)
        self._activity(f"Screenshot viewer: {target}")

    def _format_result(self, design: GeneratedDesign, run_result: RunResult | None = None) -> str:
        structured = json.dumps(design.spec.to_dict(), ensure_ascii=False, indent=2)
        interpretation = self._format_interpretation(design)
        rag_sources = "\n".join(f"- {item.title} ({item.score:.3f}) {item.url}" for item in design.rag_results) or "- Nenhuma fonte recuperada."
        run_block = ""
        if run_result:
            outputs = "\n".join(f"- {kind}: {path}" for kind, path in run_result.output_paths.items()) or "- Nenhum arquivo confirmado."
            run_block = f"\n\nExecucao FreeCAD:\n{run_result.message}\n{outputs}"
        return (
            f"Prompt:\n{design.prompt}\n\n"
            f"{interpretation}\n\n"
            f"Interpretacao estruturada:\n{structured}\n\n"
            f"{design.summary}\n\n"
            f"RAG usado:\n{rag_sources}"
            f"{run_block}"
        )

    def _format_interpretation(self, design: GeneratedDesign) -> str:
        spec = design.spec
        if spec.part_type != "flange":
            return "Interpretacao:\n" + design.summary.split("\n\n", 1)[0]
        d = spec.dimensions
        assumptions = "\n".join(f"- {item}" for item in spec.assumptions) or "- Nenhuma."
        warnings = "\n".join(f"- {item}" for item in spec.warnings) or "- Nenhum."
        return "\n".join(
            [
                "Interpretacao:",
                "Tipo: flange",
                f"Material: {spec.material or 'nao informado'}",
                f"Diametro externo: {d.get('outer_diameter', d.get('diameter'))} mm",
                f"Espessura: {d.get('thickness')} mm",
                f"Furo central: {d.get('center_hole_diameter', d.get('center_hole'))} mm",
                f"Quantidade de furos: {d.get('hole_count', 0)}",
                f"Diametro dos furos: {d.get('hole_diameter', '-')} mm",
                f"Raio usado para os furos: {d.get('bolt_circle_radius', '-')} mm",
                f"Diametro primitivo: {d.get('bolt_circle_diameter', d.get('bolt_circle', '-'))} mm",
                "",
                "Suposicoes/correcoes:",
                assumptions,
                "",
                "Avisos:",
                warnings,
                "",
                "Status: Geometria valida" if not spec.warnings else "Status: Geometria corrigida e validada",
            ]
        )

    def _refresh_export_view(self) -> None:
        output_dir = Path(self.output_dir_edit.text()).expanduser()
        files = sorted(
            [path for path in output_dir.glob("**/*") if path.is_file() and path.suffix.lower() in {".fcstd", ".step", ".stl", ".obj", ".brep", ".json", ".md", ".png"}],
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )[:80]
        self.export_view.setPlainText("\n".join(str(path) for path in files) or "Nenhum arquivo exportado.")

    def _refresh_library(self) -> None:
        lines: list[str] = []
        metadata_files = list(OUTPUT_DIR.glob("**/metadata.json")) + list(OUTPUT_DIR.glob("**/*_metadata.json"))
        for metadata_path in sorted(set(metadata_files), key=lambda path: path.stat().st_mtime, reverse=True)[:40]:
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                validation = metadata.get("validation", {})
                bbox = validation.get("bbox", {}) if isinstance(validation, dict) else {}
                lines.append(
                    f"{metadata.get('base_name', metadata_path.stem)} | "
                    f"valid={validation.get('valid')} | "
                    f"bbox={bbox.get('x_length', '-')}/{bbox.get('y_length', '-')}/{bbox.get('z_length', '-')} | "
                    f"{metadata_path}"
                )
            except Exception:
                lines.append(str(metadata_path))
        self.library_view.setPlainText("\n".join(lines) or "Biblioteca vazia.")

    def _refresh_settings(self) -> None:
        payload = {
            "freecad": self._freecad_status(),
            "output_dir": str(Path(self.output_dir_edit.text()).expanduser()),
            "macros_dir": str(MACROS_DIR),
            "rag_dir": str(RAG_DIR),
            "rag_status": self._rag_status(),
            "viewer_mode": self.viewer_mode_label.text(),
        }
        self.settings_view.setPlainText(json.dumps(payload, ensure_ascii=False, indent=2))

    def _set_busy(self, busy: bool, message: str) -> None:
        for button in (
            self.generate_button,
            self.run_button,
            self.generate_export_button,
            self.generate_view_button,
            self.test_freecad_button,
            self.rebuild_rag_button,
            self.import_run_button,
            self.doctor_button,
            self.open_part_button,
            self.open_job_button,
            self.reload_viewer_button,
            self.open_stl_button,
            self.open_step_button,
            self.clear_visual_cache_button,
            self.diagnostic_package_button,
            self.reset_app_button,
        ):
            button.setEnabled(not busy)
        self.cancel_button.setEnabled(busy)
        if busy:
            self.activity_progress.setRange(0, 0)
        else:
            self.activity_progress.setRange(0, 1)
            self.activity_progress.setValue(1)
        self._activity(message)
        self.statusBar().showMessage(message)

    def _activity(self, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        line = f"{timestamp}  {message}"
        self.activity_label.setText(message)
        self.activity_log.appendPlainText(line)
        self.log_view.appendPlainText(line)
        self.statusBar().showMessage(message)
        QApplication.processEvents()

    def _start_worker(
        self,
        func: Callable[..., Any],
        on_finished: Callable[[Any], None],
        *args: Any,
        with_progress: bool = False,
        **kwargs: Any,
    ) -> None:
        thread = QThread(self)
        worker = FunctionWorker(func, *args, emit_progress=with_progress, **kwargs)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        if with_progress:
            worker.progress.connect(self._activity)
        worker.finished.connect(on_finished)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        worker.failed.connect(self._handle_worker_error)
        worker.failed.connect(thread.quit)
        worker.failed.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda: self._cleanup_worker(thread, worker))
        self._threads.append(thread)
        self._workers.append(worker)
        thread.start()

    def _cleanup_worker(self, thread: QThread, worker: FunctionWorker) -> None:
        if thread in self._threads:
            self._threads.remove(thread)
        if worker in self._workers:
            self._workers.remove(worker)

    def _handle_worker_error(self, trace: str) -> None:
        self._set_busy(False, "Erro em tarefa")
        self._activity("Erro em tarefa. Veja detalhes abaixo.")
        self.log_view.appendPlainText(trace)
        QMessageBox.critical(self, "Erro", trace[-2400:])

    def closeEvent(self, event) -> None:
        if self._threads:
            ProcessRunner.cancel_all()
            for thread in list(self._threads):
                thread.quit()
                thread.wait(3000)
        super().closeEvent(event)
