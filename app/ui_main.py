from __future__ import annotations

import json
import inspect
import re
import subprocess
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtGui import QAction, QColor, QCursor, QFont
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
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QMenu,
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
from app.freecad_runner import discover_freecad_binaries, find_freecad_executable, run_macro
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
from app.viewer3d.inspection import InspectionResult, load_metadata_for_mesh, run_inspection
from app.viewer3d.inspection_report import write_inspection_report
from app.viewer3d.mesh_viewer import create_mesh_viewer
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
        self.setWindowFlags(
            Qt.Window
            | Qt.WindowSystemMenuHint
            | Qt.WindowMinimizeButtonHint
            | Qt.WindowMaximizeButtonHint
            | Qt.WindowCloseButtonHint
        )
        self.setMinimumSize(1280, 800)
        self.resize(1500, 950)
        self.rag = LocalRagStore()
        self.agent = PromptAgent(self.rag)
        self.current_design: GeneratedDesign | None = None
        self.last_run_result: RunResult | None = None
        self.current_job_result: CadJobResult | None = None
        self._current_mesh_path: Path | None = None
        self._current_display_mesh_path: Path | None = None
        self._current_using_preview = False
        self._last_selection_payload: dict[str, object] | None = None
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
        self.viewer_mode_label = QLabel("carregando")
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

        self.viewer = create_mesh_viewer()
        self.viewer_mode_label.setText("vtk" if self.viewer.__class__.__name__ == "VTKMeshViewer" else "mesh_fallback")
        if hasattr(self.viewer, "measurementChanged"):
            self.viewer.measurementChanged.connect(self._handle_measurement_changed)
        if hasattr(self.viewer, "selectionChanged"):
            self.viewer.selectionChanged.connect(self._handle_selection_changed)
        if hasattr(self.viewer, "contextMenuRequested"):
            self.viewer.contextMenuRequested.connect(self._show_viewer_context_menu)
        self.viewer_status_label = QLabel("Nenhuma malha carregada")
        self.viewer_dimensions_label = QLabel("Dimensoes: -")
        self.viewer_measure_label = QLabel("Medida: -")
        self.viewer_selection_label = QLabel("Selecao: camera")
        self.selection_mode_combo = QComboBox()
        self.selection_mode_combo.addItem("Camera", "camera")
        self.selection_mode_combo.addItem("Objeto", "object")
        self.selection_mode_combo.addItem("Face", "face")
        self.selection_mode_combo.addItem("Edge", "edge")
        self.selection_mode_combo.addItem("Ponto", "point")
        self.object_tree = QTreeWidget()
        self.object_tree.setHeaderLabels(["Objeto", "Valor"])
        self.inspection_result: InspectionResult | None = None
        self.viewer_inspection_summary_label = QLabel("Inspecao: nenhuma peca carregada")
        self.inspection_summary_label = QLabel("Inspecao: nenhuma peca carregada")
        self.inspection_tolerance_combo = QComboBox()
        self.inspection_tolerance_combo.addItems(["0.01", "0.05", "0.10", "0.20", "0.50", "1.00"])
        self.inspection_tolerance_combo.setCurrentText("0.20")
        self.inspection_tree = QTreeWidget()
        self.inspection_tree.setHeaderLabels(["Item", "Esperado", "Medido", "Erro", "Tol.", "Status"])
        self.export_inspection_button = self._button("Exportar Relatorio", QStyle.SP_DialogSaveButton)

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
        self.tabs.addTab(self._inspection_tab(), "Inspecao CAD")
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

        self.display_combo = QComboBox()
        self.display_combo.addItems(["shaded", "shaded_with_edges", "wireframe"])
        self.display_combo.currentTextChanged.connect(self.viewer.set_display_mode)
        controls.addWidget(self.display_combo)

        lod_button = QPushButton("Preview/Completo")
        lod_button.clicked.connect(self.toggle_mesh_lod)
        controls.addWidget(lod_button)

        controls.addWidget(QLabel("Selecionar"))
        self.selection_mode_combo.currentIndexChanged.connect(self._change_selection_mode)
        controls.addWidget(self.selection_mode_combo)

        self.measure_check = QCheckBox("Medir")
        self.measure_check.toggled.connect(self._toggle_measurement)
        controls.addWidget(self.measure_check)

        clear_measure_button = QPushButton("Limpar medicoes")
        clear_measure_button.clicked.connect(self.clear_measurements)
        controls.addWidget(clear_measure_button)

        self.axes_check = QCheckBox("Eixos")
        self.axes_check.setChecked(False)
        self.axes_check.toggled.connect(self._toggle_axes)
        controls.addWidget(self.axes_check)

        self.bbox_check = QCheckBox("BBox")
        self.bbox_check.setChecked(False)
        self.bbox_check.toggled.connect(self._toggle_bbox)
        controls.addWidget(self.bbox_check)

        self.dimensions_check = QCheckBox("Cotas")
        self.dimensions_check.setChecked(False)
        self.dimensions_check.toggled.connect(lambda checked: self._toggle_viewer_feature("dimensions", checked))
        controls.addWidget(self.dimensions_check)

        self.pcd_check = QCheckBox("PCD")
        self.pcd_check.setChecked(False)
        self.pcd_check.toggled.connect(lambda checked: self._toggle_viewer_feature("pcd", checked))
        controls.addWidget(self.pcd_check)

        self.holes_check = QCheckBox("Furos")
        self.holes_check.setChecked(False)
        self.holes_check.toggled.connect(lambda checked: self._toggle_viewer_feature("holes", checked))
        controls.addWidget(self.holes_check)

        self.grid_check = QCheckBox("Grade")
        self.grid_check.setChecked(False)
        self.grid_check.toggled.connect(lambda checked: self._toggle_viewer_feature("grid", checked))
        controls.addWidget(self.grid_check)

        material_button = QPushButton("Cor Peca")
        material_button.clicked.connect(self._choose_material_color)
        controls.addWidget(material_button)

        bg_button = QPushButton("Cor Fundo")
        bg_button.clicked.connect(self._choose_background_color)
        controls.addWidget(bg_button)

        screenshot_button = QPushButton("PNG")
        screenshot_button.clicked.connect(self.export_viewer_png)
        controls.addWidget(screenshot_button)

        report_button = QPushButton("Relatorio")
        report_button.clicked.connect(self.export_inspection_report)
        controls.addWidget(report_button)

        self.viewer_alpha_slider = QSlider(Qt.Horizontal)
        self.viewer_alpha_slider.setRange(20, 255)
        self.viewer_alpha_slider.setValue(245)
        self.viewer_alpha_slider.setFixedWidth(110)
        self.viewer_alpha_slider.valueChanged.connect(self._set_viewer_alpha)
        controls.addWidget(QLabel("Alpha"))
        controls.addWidget(self.viewer_alpha_slider)
        controls.addStretch(1)

        body = QSplitter()
        body.addWidget(self.viewer)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.addWidget(self.viewer_status_label)
        right_layout.addWidget(self.viewer_dimensions_label)
        right_layout.addWidget(self.viewer_selection_label)
        right_layout.addWidget(self.viewer_measure_label)
        right_layout.addWidget(self.viewer_inspection_summary_label)
        right_layout.addWidget(self.object_tree)
        right_layout.addWidget(self._cad_tools_group())
        body.addWidget(right)
        body.setSizes([720, 260])

        layout.addLayout(controls)
        layout.addWidget(body)
        return tab

    def _cad_tools_group(self) -> QGroupBox:
        group = QGroupBox("Operacoes CAD")
        layout = QVBoxLayout(group)
        self.cad_op_command_edit = QLineEdit()
        self.cad_op_command_edit.setPlaceholderText("CAD_OP: subtract_cylinder diameter=8 height=12 x=50 y=50 z=-1 axis=z")
        layout.addWidget(self.cad_op_command_edit)

        row_a = QHBoxLayout()
        for label, callback in (
            ("+ Box", lambda: self._cad_operation_dialog("Adicionar box", "add_box", self._default_box_operation())),
            ("+ Cilindro", lambda: self._cad_operation_dialog("Adicionar cilindro", "add_cylinder", self._default_cylinder_operation(add=True))),
            ("- Furo", lambda: self._cad_operation_dialog("Furo cilindrico", "subtract_cylinder", self._default_cylinder_operation(add=False))),
            ("- Box", lambda: self._cad_operation_dialog("Subtrair box", "subtract_box", self._default_box_operation())),
        ):
            button = QPushButton(label)
            button.clicked.connect(callback)
            row_a.addWidget(button)
        layout.addLayout(row_a)

        row_b = QHBoxLayout()
        for label, callback in (
            ("Mover Face", self._cad_move_selected_face),
            ("Linha Face", self._cad_line_on_selected_face),
            ("Aplicar Op", self._append_cad_operation_from_field),
            ("Gerar CAD", self.generate_execute_visualize),
        ):
            button = QPushButton(label)
            button.clicked.connect(callback)
            row_b.addWidget(button)
        layout.addLayout(row_b)
        return group

    def _inspection_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(12, 12, 12, 12)
        top = QHBoxLayout()
        top.addWidget(QLabel("Tolerancia"))
        top.addWidget(self.inspection_tolerance_combo)
        top.addWidget(self.export_inspection_button)
        top.addStretch(1)
        layout.addLayout(top)
        layout.addWidget(self.inspection_summary_label)
        layout.addWidget(self.inspection_tree)
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
        self.export_inspection_button.clicked.connect(self.export_inspection_report)

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
        if hasattr(self.viewer, "clear"):
            self.viewer.clear()
        elif hasattr(self.viewer, "scene"):
            self.viewer.scene().clear()
        self.object_tree.clear()
        self.inspection_tree.clear()
        self.inspection_result = None
        self._current_mesh_path = None
        self._current_display_mesh_path = None
        self._current_using_preview = False
        self._last_selection_payload = None
        self.viewer_status_label.setText("Viewer limpo")
        self.viewer_dimensions_label.setText("Dimensoes: -")
        self.viewer_measure_label.setText("Medida: -")
        self.viewer_selection_label.setText("Selecao: camera")
        self.viewer_inspection_summary_label.setText("Inspecao: nenhuma peca carregada")
        self.inspection_summary_label.setText("Inspecao: nenhuma peca carregada")
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
        freecad = self._freecad_gui_executable()
        if not freecad:
            QMessageBox.warning(self, "Abrir peca", "FreeCAD nao foi encontrado.")
            return
        self._activity(f"Abrindo peca no FreeCAD: {fcstd.name}")
        log_path = Path(self.output_dir_edit.text()).expanduser().parent / "logs" / "opened_freecad.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        opener = self._write_freecad_open_script(fcstd)
        with log_path.open("ab") as log_handle:
            subprocess.Popen([freecad, str(opener)], stdout=log_handle, stderr=subprocess.STDOUT)

    def _write_freecad_open_script(self, fcstd: Path) -> Path:
        script_path = Path(self.output_dir_edit.text()).expanduser().parent / "logs" / "open_latest_part.py"
        script_path.parent.mkdir(parents=True, exist_ok=True)
        script_path.write_text(
            "\n".join(
                [
                    "import FreeCAD as App",
                    "import FreeCADGui as Gui",
                    "",
                    "def _safe(callable_obj, *args):",
                    "    try:",
                    "        return callable_obj(*args)",
                    "    except Exception:",
                    "        return None",
                    "",
                    "def _valid_shape_object(obj):",
                    "    try:",
                    "        shape = getattr(obj, 'Shape', None)",
                    "        if shape is None or shape.isNull():",
                    "            return False",
                    "        return bool(getattr(shape, 'Solids', [])) or bool(getattr(shape, 'Faces', []))",
                    "    except Exception:",
                    "        return False",
                    "",
                    "def _shape_score(obj):",
                    "    try:",
                    "        shape = getattr(obj, 'Shape', None)",
                    "        solids = len(getattr(shape, 'Solids', []))",
                    "        faces = len(getattr(shape, 'Faces', []))",
                    "        volume = abs(float(getattr(shape, 'Volume', 0.0)))",
                    "        area = abs(float(getattr(shape, 'Area', 0.0)))",
                    "        return (solids, volume, faces, area)",
                    "    except Exception:",
                    "        return (0, 0.0, 0, 0.0)",
                    "",
                    "def _make_visible(obj):",
                    "    if obj is None:",
                    "        return",
                    "    _safe(setattr, obj, 'Visibility', True)",
                    "    view = getattr(obj, 'ViewObject', None)",
                    "    if view is not None:",
                    "        _safe(setattr, view, 'Visibility', True)",
                    "        _safe(setattr, view, 'DisplayMode', 'Flat Lines')",
                    "",
                    f"doc = App.openDocument({str(fcstd)!r})",
                    "_safe(App.setActiveDocument, doc.Name)",
                    "_safe(Gui.showMainWindow)",
                    "main_window = _safe(Gui.getMainWindow)",
                    "if main_window is not None:",
                    "    _safe(main_window.showMaximized)",
                    "_safe(Gui.activateWorkbench, 'PartWorkbench')",
                    "doc.recompute()",
                    "gui_doc = Gui.getDocument(doc.Name) or Gui.ActiveDocument",
                    "final_obj = doc.getObject('Final_GeneratedPart')",
                    "if final_obj is None or not _valid_shape_object(final_obj):",
                    "    role_matches = [obj for obj in doc.Objects if getattr(obj, 'PromptForgeRole', '') == 'final' and _valid_shape_object(obj)]",
                    "    shape_matches = [obj for obj in doc.Objects if _valid_shape_object(obj)]",
                    "    candidates = role_matches or shape_matches",
                    "    final_obj = sorted(candidates, key=_shape_score, reverse=True)[0] if candidates else None",
                    "parents = set(getattr(final_obj, 'InListRecursive', []) or []) if final_obj is not None else set()",
                    "for parent in parents:",
                    "    _make_visible(parent)",
                    "for obj in doc.Objects:",
                    "    try:",
                    "        if obj is final_obj or obj in parents:",
                    "            continue",
                    "        role = getattr(obj, 'PromptForgeRole', '')",
                    "        if role and role != 'final' and hasattr(obj, 'ViewObject'):",
                    "            obj.ViewObject.Visibility = False",
                    "    except Exception:",
                    "        pass",
                    "if final_obj is not None:",
                    "    _make_visible(final_obj)",
                    "    _safe(Gui.Selection.clearSelection)",
                    "    _safe(Gui.Selection.addSelection, final_obj)",
                    "    print('[PromptForge] visible object:', final_obj.Name, final_obj.Label)",
                    "else:",
                    "    print('[PromptForge] warning: no renderable shape object found')",
                    "doc.recompute()",
                    "view = getattr(gui_doc, 'ActiveView', None)",
                    "if view is not None:",
                    "    _safe(view.viewIsometric)",
                    "    _safe(view.fitAll)",
                    "    _safe(Gui.SendMsgToActiveView, 'ViewAxo')",
                    "    _safe(Gui.SendMsgToActiveView, 'ViewFit')",
                    "else:",
                    "    print('[PromptForge] warning: no active 3D view available')",
                    "_safe(Gui.updateGui)",
                    "print('[PromptForge] opened and fitted:', doc.FileName)",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        return script_path

    def _freecad_gui_executable(self) -> str | None:
        for binary in discover_freecad_binaries():
            name = Path(binary.path).name.lower()
            if "cmd" not in name and "console" not in name:
                return binary.path
        return find_freecad_executable()

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
        if result.ok and (result.display_mesh_path or result.mesh_path):
            display_path = Path(result.display_mesh_path or result.mesh_path)
            self._current_mesh_path = Path(result.mesh_path) if result.mesh_path else display_path
            self._current_display_mesh_path = display_path
            self._current_using_preview = self._current_mesh_path.resolve() != display_path.resolve()
            topology_path = self._topology_path_for_mesh(self._current_mesh_path)
            if topology_path and hasattr(self.viewer, "load_topology"):
                status = self.viewer.load_topology(topology_path)
                self.viewer_mode_label.setText("vtk_topology")
                self._activity(f"Topologia CAD carregada: {topology_path.name}.")
            elif hasattr(self.viewer, "load_mesh"):
                status = self.viewer.load_mesh(display_path)
            else:
                status = self.viewer.set_mesh_data(result.vertices, result.faces, result.mesh_path)
            self.viewer_status_label.setText(status.message)
            if result.mesh_path:
                self._update_viewer_metadata(Path(result.mesh_path), result)
            self._activity(f"Peca carregada no viewer ({result.viewer_mode}, {result.lod_mode}, {result.load_seconds:.2f}s).")
            self.tabs.setCurrentIndex(1)
        elif result.preview_images:
            self._activity("Viewer 3D indisponivel; previews PNG foram gerados no job.")
            self.export_view.setPlainText("\n".join(str(path) for path in result.preview_images.values()))
            self.tabs.setCurrentWidget(self.export_view)
        else:
            self._activity(f"Arquivo STL/OBJ gerado, mas falhou ao carregar no viewer. {result.error}")

    def _topology_path_for_mesh(self, mesh_path: Path | None) -> Path | None:
        if mesh_path is None:
            return None
        metadata, _metadata_path = load_metadata_for_mesh(mesh_path)
        files = metadata.get("files") if isinstance(metadata, dict) else {}
        candidates: list[Path] = []
        for key in ("topology", "topology_json"):
            value = files.get(key) if isinstance(files, dict) else None
            if value:
                candidates.append(Path(value))
        topology = metadata.get("topology") if isinstance(metadata, dict) else None
        if isinstance(topology, dict):
            for key in ("path", "canonical_path"):
                value = topology.get(key)
                if value:
                    candidates.append(Path(value))
        candidates.extend([mesh_path.parent / "topology.json", *sorted(mesh_path.parent.glob("*_topology.json"))])
        for candidate in candidates:
            candidate = candidate.expanduser()
            if candidate.exists():
                return candidate
        return None

    def _update_viewer_metadata(self, mesh_path: Path, result: ViewerWorkerResult | None = None) -> None:
        self.object_tree.clear()
        self.object_tree.addTopLevelItem(QTreeWidgetItem(["Arquivo", str(mesh_path)]))
        stats = self.viewer.get_mesh_stats() if hasattr(self.viewer, "get_mesh_stats") else {}
        bbox = dict(result.bbox if result and result.bbox else stats.get("bbox", {}))
        if not bbox and getattr(self.viewer, "vertices", None) is not None:
            import numpy as np

            vertices = self.viewer.vertices
            mins = vertices.min(axis=0)
            maxs = vertices.max(axis=0)
            lengths = maxs - mins
            bbox = {
                "x": float(lengths[0]),
                "y": float(lengths[1]),
                "z": float(lengths[2]),
                "xmin": float(mins[0]),
                "xmax": float(maxs[0]),
                "ymin": float(mins[1]),
                "ymax": float(maxs[1]),
                "zmin": float(mins[2]),
                "zmax": float(maxs[2]),
            }
        x = float(bbox.get("x", 0.0) or 0.0)
        y = float(bbox.get("y", 0.0) or 0.0)
        z = float(bbox.get("z", 0.0) or 0.0)
        diagonal = (x * x + y * y + z * z) ** 0.5
        self.viewer_dimensions_label.setText(f"Dimensoes: X={x:.3f} Y={y:.3f} Z={z:.3f}")
        self.viewer_measure_label.setText(f"Medida: diagonal BBox={diagonal:.3f}")
        metadata, metadata_path = load_metadata_for_mesh(mesh_path)
        if metadata and hasattr(self.viewer, "set_inspection_metadata"):
            self.viewer.set_inspection_metadata(metadata)
        freecad_standard = metadata.get("freecad_standard") if isinstance(metadata, dict) else None
        if isinstance(freecad_standard, dict):
            tree_root = QTreeWidgetItem(
                [
                    "Arvore FreeCAD 1.1",
                    str(freecad_standard.get("container") or freecad_standard.get("final_object") or "-"),
                ]
            )
            for item in freecad_standard.get("project_tree") or []:
                if not isinstance(item, dict):
                    continue
                label = str(item.get("label") or item.get("name") or "-")
                role = str(item.get("role") or "-")
                child = QTreeWidgetItem([label, role])
                child.addChild(QTreeWidgetItem(["Tipo", str(item.get("type", "-"))]))
                child.addChild(QTreeWidgetItem(["Operacao", str(item.get("operation", "-"))]))
                child.addChild(QTreeWidgetItem(["Objeto", str(item.get("name", "-"))]))
                tree_root.addChild(child)
            self.object_tree.addTopLevelItem(tree_root)
        mesh_stats = {
            "bbox": bbox,
            "triangles": result.face_count if result else stats.get("triangles"),
            "points": result.vertex_count if result else stats.get("points"),
        }
        tolerance = float(self.inspection_tolerance_combo.currentText())
        self.inspection_result = run_inspection(metadata, mesh_stats, tolerance=tolerance, metadata_path=metadata_path)
        self._populate_inspection_tree(self.inspection_result)
        summary = f"Inspecao: {self.inspection_result.overall_status}"
        self.inspection_summary_label.setText(summary)
        self.viewer_inspection_summary_label.setText(summary)
        for key, value in (
            ("Engine", stats.get("engine", result.viewer_mode if result else "-")),
            ("Modo LOD", result.lod_mode if result else "complete"),
            ("Tempo load", f"{result.load_seconds:.3f}s" if result else "-"),
            ("Pontos renderizados", stats.get("points", result.vertex_count if result else "-")),
            ("Triangulos renderizados", stats.get("triangles", result.face_count if result else "-")),
            ("Pontos originais", result.original_vertex_count if result else stats.get("points", "-")),
            ("Triangulos originais", result.original_face_count if result else stats.get("triangles", "-")),
            ("Faces CAD", stats.get("topology_faces", "-")),
            ("Edges CAD", stats.get("topology_edges", "-")),
            ("X", f"{x:.3f}"),
            ("Y", f"{y:.3f}"),
            ("Z", f"{z:.3f}"),
        ):
            self.object_tree.addTopLevelItem(QTreeWidgetItem([str(key), str(value)]))
        self.object_tree.expandAll()

    def toggle_mesh_lod(self) -> None:
        if not self._current_mesh_path:
            self._activity("Nenhuma malha carregada para alternar preview/completo.")
            return
        if not self._current_display_mesh_path or self._current_display_mesh_path.resolve() == self._current_mesh_path.resolve():
            self._activity("Malha atual ja esta em modo completo; nenhum preview decimado disponivel.")
            return
        target = self._current_mesh_path if self._current_using_preview else self._current_display_mesh_path
        mode = "completo" if target.resolve() == self._current_mesh_path.resolve() else "preview"
        self._activity(f"Alternando viewer para modo {mode}: {target.name}")
        status = self.viewer.load_mesh(target) if hasattr(self.viewer, "load_mesh") else None
        self._current_using_preview = target.resolve() != self._current_mesh_path.resolve()
        if status is not None:
            self.viewer_status_label.setText(f"{status.message} ({mode})")
        self._update_viewer_metadata(self._current_mesh_path, None)

    def _populate_inspection_tree(self, inspection: InspectionResult) -> None:
        self.inspection_tree.clear()
        for check in inspection.checks:
            self.inspection_tree.addTopLevelItem(
                QTreeWidgetItem(
                    [
                        check.name,
                        "-" if check.expected is None else str(check.expected),
                        "-" if check.measured is None else str(check.measured),
                        "-" if check.error is None else f"{check.error:.4f}",
                        "-" if check.tolerance is None else str(check.tolerance),
                        check.status,
                    ]
                )
            )
        self.inspection_tree.expandAll()

    def _toggle_axes(self, checked: bool) -> None:
        if hasattr(self.viewer, "set_show_axes"):
            self.viewer.set_show_axes(checked)
        else:
            self.viewer.show_axes = checked
            self.viewer.render_scene()

    def _toggle_bbox(self, checked: bool) -> None:
        if hasattr(self.viewer, "set_show_bounding_box"):
            self.viewer.set_show_bounding_box(checked)
        else:
            self.viewer.show_bbox = checked
            self.viewer.render_scene()

    def _toggle_viewer_feature(self, feature: str, checked: bool) -> None:
        method_by_feature = {
            "grid": "set_show_grid",
            "dimensions": "set_show_dimensions",
            "pcd": "set_show_pcd",
            "holes": "set_show_hole_centers",
        }
        method_name = method_by_feature.get(feature)
        if method_name and hasattr(self.viewer, method_name):
            getattr(self.viewer, method_name)(checked)
        elif hasattr(self.viewer, "render_scene"):
            self.viewer.render_scene()

    def _change_selection_mode(self) -> None:
        mode = self.selection_mode_combo.currentData() or "camera"
        if hasattr(self.viewer, "set_selection_mode"):
            self.viewer.set_selection_mode(str(mode))
        self.viewer_selection_label.setText(f"Selecao: {self.selection_mode_combo.currentText()}")
        self._activity(f"Modo de selecao: {self.selection_mode_combo.currentText()}.")

    def _toggle_measurement(self, checked: bool) -> None:
        if hasattr(self.viewer, "set_measurement_enabled"):
            self.viewer.set_measurement_enabled(checked)
        mode = self.selection_mode_combo.currentText()
        self._activity(f"Medicao ativada para selecao: {mode}." if checked else "Medicao desativada.")

    def clear_measurements(self) -> None:
        if hasattr(self.viewer, "clear_measurements"):
            self.viewer.clear_measurements()
        self.viewer_measure_label.setText("Medida: -")

    def _show_viewer_context_menu(self, payload: dict[str, object]) -> None:
        menu = QMenu("Visualizador CAD", self)

        def add_action(label: str, callback: Callable[[], None], enabled: bool = True) -> QAction:
            action = menu.addAction(label)
            action.setEnabled(enabled)
            action.triggered.connect(lambda _checked=False: callback())
            return action

        def add_mode(label: str, mode: str) -> None:
            action = menu.addAction(label)
            action.setCheckable(True)
            action.setChecked((self.selection_mode_combo.currentData() or "camera") == mode)
            action.triggered.connect(lambda _checked=False, selected=mode: self._set_selection_mode_from_menu(selected))

        def add_display(label: str, mode: str) -> None:
            action = menu.addAction(label)
            action.setCheckable(True)
            current = self.display_combo.currentText() if hasattr(self, "display_combo") else ""
            action.setChecked(current == mode)
            action.triggered.connect(lambda _checked=False, selected=mode: self._set_display_mode_from_menu(selected))

        def add_toggle(label: str, checkbox: QCheckBox | None) -> None:
            action = menu.addAction(label)
            action.setCheckable(True)
            if checkbox is None:
                action.setEnabled(False)
                return
            action.setChecked(checkbox.isChecked())
            action.triggered.connect(lambda checked=False, widget=checkbox: widget.setChecked(bool(checked)))

        add_mode("Selecionar objeto inteiro", "object")
        add_mode("Selecionar face", "face")
        add_mode("Selecionar edge", "edge")
        add_mode("Selecionar ponto", "point")
        add_mode("Modo camera / navegar", "camera")
        menu.addSeparator()
        add_toggle("Medir selecao", getattr(self, "measure_check", None))
        add_action("Limpar selecao", self._clear_current_selection)
        add_action("Limpar medicoes", self.clear_measurements)
        menu.addSeparator()
        add_action("Zoom na peca", self.viewer.zoom_extents if hasattr(self.viewer, "zoom_extents") else self.reload_viewer)
        add_action("Vista isometrica", lambda: self.viewer.set_view("isometric"), hasattr(self.viewer, "set_view"))
        add_action("Vista frontal", lambda: self.viewer.set_view("front"), hasattr(self.viewer, "set_view"))
        add_action("Vista superior", lambda: self.viewer.set_view("top"), hasattr(self.viewer, "set_view"))
        add_action("Vista lateral", lambda: self.viewer.set_view("side"), hasattr(self.viewer, "set_view"))
        menu.addSeparator()
        add_display("Exibicao sombreada", "shaded")
        add_display("Exibicao com arestas", "shaded_with_edges")
        add_display("Wireframe", "wireframe")
        menu.addSeparator()
        add_toggle("Mostrar eixos", getattr(self, "axes_check", None))
        add_toggle("Mostrar caixa BBox", getattr(self, "bbox_check", None))
        add_toggle("Mostrar cotas", getattr(self, "dimensions_check", None))
        add_toggle("Mostrar PCD", getattr(self, "pcd_check", None))
        add_toggle("Mostrar centros dos furos", getattr(self, "holes_check", None))
        add_toggle("Mostrar grade", getattr(self, "grid_check", None))
        menu.addSeparator()
        add_action("Copiar dados da selecao", self._copy_selection_to_clipboard, self._last_selection_payload is not None)
        add_action("Exportar imagem PNG", self.export_viewer_png, hasattr(self.viewer, "export_png"))
        add_action("Gerar relatorio de inspecao", self.export_inspection_report, self.inspection_result is not None)
        menu.addSeparator()
        add_action("CAD: adicionar box", lambda: self._cad_operation_dialog("Adicionar box", "add_box", self._default_box_operation()))
        add_action("CAD: adicionar cilindro", lambda: self._cad_operation_dialog("Adicionar cilindro", "add_cylinder", self._default_cylinder_operation(add=True)))
        add_action("CAD: furar/subtrair cilindro", lambda: self._cad_operation_dialog("Furo cilindrico", "subtract_cylinder", self._default_cylinder_operation(add=False)))
        add_action("CAD: mover face selecionada", self._cad_move_selected_face)
        add_action("CAD: linha na face", self._cad_line_on_selected_face)
        add_action("CAD: gerar com operacoes", self.generate_execute_visualize)
        menu.addSeparator()
        add_action("Recarregar visualizador", self.reload_viewer)
        add_action("Abrir pasta do job", self.open_job_dir)
        add_action("Abrir peca no FreeCAD", self.open_latest_part)
        add_action("Limpar cache visual", self.clear_visual_cache)
        self._activity(
            "Menu do viewer: "
            f"modo={payload.get('selection_mode', '-')}, engine={payload.get('engine', '-')}, "
            f"topologia={'sim' if payload.get('has_topology') else 'nao'}."
        )
        menu.exec(QCursor.pos())

    def _set_selection_mode_from_menu(self, mode: str) -> None:
        index = self.selection_mode_combo.findData(mode)
        if index >= 0:
            self.selection_mode_combo.setCurrentIndex(index)

    def _set_display_mode_from_menu(self, mode: str) -> None:
        if hasattr(self, "display_combo"):
            index = self.display_combo.findText(mode)
            if index >= 0:
                self.display_combo.setCurrentIndex(index)
        elif hasattr(self.viewer, "set_display_mode"):
            self.viewer.set_display_mode(mode)

    def _clear_current_selection(self) -> None:
        if hasattr(self.viewer, "clear_selection"):
            self.viewer.clear_selection()
        self._last_selection_payload = None
        self.viewer_selection_label.setText(f"Selecao: {self.selection_mode_combo.currentText()}")
        for index in range(self.object_tree.topLevelItemCount() - 1, -1, -1):
            if self.object_tree.topLevelItem(index).text(0) == "Selecao atual":
                self.object_tree.takeTopLevelItem(index)
        self._activity("Selecao visual limpa.")

    def _copy_selection_to_clipboard(self) -> None:
        if self._last_selection_payload is None:
            QApplication.clipboard().setText("Nenhuma selecao ativa.")
            self._activity("Nenhuma selecao ativa para copiar.")
            return
        text = json.dumps(self._last_selection_payload, ensure_ascii=False, indent=2, default=str)
        QApplication.clipboard().setText(text)
        self._activity("Dados da selecao copiados para a area de transferencia.")

    def _append_cad_operation(self, operation: str, params: dict[str, object], run_now: bool = False) -> None:
        serialized = " ".join(f"{key}={self._cad_param_value(value)}" for key, value in params.items() if value is not None)
        directive = f"[CAD_OP {operation} {serialized}]".strip()
        current = self.prompt_edit.toPlainText().rstrip()
        self.prompt_edit.setPlainText(f"{current}\n{directive}".strip())
        self._activity(f"Operacao CAD adicionada ao prompt: {directive}")
        if run_now:
            self.generate_execute_visualize()

    def _cad_param_value(self, value: object) -> str:
        if isinstance(value, float):
            text = f"{value:.4f}".rstrip("0").rstrip(".")
            return text or "0"
        return str(value).replace(" ", "_")

    def _parse_key_value_text(self, text: str) -> dict[str, object]:
        params: dict[str, object] = {}
        for key, raw_value in re.findall(r"([a-zA-Z_][a-zA-Z0-9_]*)=('[^']*'|\"[^\"]*\"|[^\s\]]+)", text):
            value = raw_value.strip().strip("'\"")
            try:
                params[key] = float(value.replace(",", "."))
            except ValueError:
                params[key] = value
        return params

    def _append_cad_operation_from_field(self) -> None:
        text = self.cad_op_command_edit.text().strip() if hasattr(self, "cad_op_command_edit") else ""
        if not text:
            QMessageBox.information(self, "Operacao CAD", "Digite uma operacao, por exemplo: subtract_cylinder diameter=8 height=12 x=50 y=50 z=-1 axis=z")
            return
        if text.startswith("[CAD_OP"):
            current = self.prompt_edit.toPlainText().rstrip()
            self.prompt_edit.setPlainText(f"{current}\n{text}".strip())
            self._activity(f"Operacao CAD adicionada ao prompt: {text}")
            return
        operation, _, params_text = text.partition(" ")
        self._append_cad_operation(operation.strip(), self._parse_key_value_text(params_text))

    def _cad_operation_dialog(self, title: str, operation: str, defaults: dict[str, object]) -> None:
        default_text = " ".join(f"{key}={self._cad_param_value(value)}" for key, value in defaults.items())
        text, ok = QInputDialog.getText(self, title, "Parametros key=value", QLineEdit.Normal, default_text)
        if not ok:
            return
        params = self._parse_key_value_text(text)
        self._append_cad_operation(operation, params or defaults)

    def _viewer_bbox(self) -> dict[str, float]:
        if hasattr(self.viewer, "get_mesh_stats"):
            stats = self.viewer.get_mesh_stats()
            bbox = stats.get("bbox") if isinstance(stats, dict) else {}
            if isinstance(bbox, dict):
                return {str(key): float(value) for key, value in bbox.items() if isinstance(value, (int, float))}
        return {}

    def _selection_or_bbox_center(self) -> tuple[float, float, float]:
        payload = self._last_selection_payload or {}
        for key in ("centroid", "point"):
            value = payload.get(key)
            if isinstance(value, (tuple, list)) and len(value) >= 3:
                return float(value[0]), float(value[1]), float(value[2])
        circular = payload.get("circular")
        if isinstance(circular, dict):
            center = circular.get("center")
            if isinstance(center, (tuple, list)) and len(center) >= 3:
                return float(center[0]), float(center[1]), float(center[2])
        bbox = self._viewer_bbox()
        return (
            (float(bbox.get("xmin", 0.0)) + float(bbox.get("xmax", bbox.get("x", 0.0)))) / 2.0,
            (float(bbox.get("ymin", 0.0)) + float(bbox.get("ymax", bbox.get("y", 0.0)))) / 2.0,
            (float(bbox.get("zmin", 0.0)) + float(bbox.get("zmax", bbox.get("z", 0.0)))) / 2.0,
        )

    def _default_box_operation(self) -> dict[str, object]:
        x, y, z = self._selection_or_bbox_center()
        return {"length": 10.0, "width": 10.0, "height": 5.0, "x": x - 5.0, "y": y - 5.0, "z": z}

    def _default_cylinder_operation(self, add: bool) -> dict[str, object]:
        x, y, _z = self._selection_or_bbox_center()
        bbox = self._viewer_bbox()
        height = max(float(bbox.get("z", 10.0) or 10.0) + 2.0, 2.0)
        z = float(bbox.get("zmin", 0.0)) - 1.0 if not add else float(bbox.get("zmax", 0.0))
        return {"diameter": 6.0, "height": height, "x": x, "y": y, "z": z, "axis": "z"}

    def _cad_move_selected_face(self) -> None:
        payload = self._last_selection_payload or {}
        if payload.get("type") != "selection_face":
            QMessageBox.information(self, "Mover face", "Selecione uma face antes de criar a operacao.")
            return
        bbox = payload.get("bbox")
        normal = payload.get("normal")
        if not isinstance(bbox, dict) or not isinstance(normal, (tuple, list)) or len(normal) < 3:
            QMessageBox.information(self, "Mover face", "A face selecionada nao tem topologia suficiente para mover.")
            return
        distance, ok = QInputDialog.getDouble(self, "Mover face", "Distancia mm (+ expande, - corta)", 5.0, -1000.0, 1000.0, 2)
        if not ok or abs(distance) < 1e-9:
            return
        nx, ny, nz = float(normal[0]), float(normal[1]), float(normal[2])
        xmin, xmax = float(bbox.get("xmin", 0.0)), float(bbox.get("xmax", 0.0))
        ymin, ymax = float(bbox.get("ymin", 0.0)), float(bbox.get("ymax", 0.0))
        zmin, zmax = float(bbox.get("zmin", 0.0)), float(bbox.get("zmax", 0.0))
        op = "add_box" if distance > 0 else "subtract_box"
        amount = abs(distance)
        if abs(nz) >= abs(nx) and abs(nz) >= abs(ny):
            z = zmax if nz >= 0 and distance > 0 else zmin - amount
            params = {"length": max(xmax - xmin, 0.1), "width": max(ymax - ymin, 0.1), "height": amount, "x": xmin, "y": ymin, "z": z}
        elif abs(nx) >= abs(ny):
            x = xmax if nx >= 0 and distance > 0 else xmin - amount
            params = {"length": amount, "width": max(ymax - ymin, 0.1), "height": max(zmax - zmin, 0.1), "x": x, "y": ymin, "z": zmin}
        else:
            y = ymax if ny >= 0 and distance > 0 else ymin - amount
            params = {"length": max(xmax - xmin, 0.1), "width": amount, "height": max(zmax - zmin, 0.1), "x": xmin, "y": y, "z": zmin}
        self._append_cad_operation(op, params)

    def _cad_line_on_selected_face(self) -> None:
        x, y, z = self._selection_or_bbox_center()
        default = f"x={x - 20:.3f} y={y:.3f} z={z:.3f} length=40 width=1 height=0.6"
        text, ok = QInputDialog.getText(self, "Linha na face", "Linha retangular fina no plano XY", QLineEdit.Normal, default)
        if not ok:
            return
        params = self._parse_key_value_text(text)
        params.setdefault("height", 0.6)
        self._append_cad_operation("add_box", params)

    def _handle_selection_changed(self, payload: dict[str, object]) -> None:
        self._last_selection_payload = dict(payload)
        kind = str(payload.get("type", "selection"))
        if kind == "selection_object":
            bbox = payload.get("bbox") or {}
            if isinstance(bbox, dict):
                self.viewer_selection_label.setText(
                    "Objeto: {tri} triangulos, {pts} pontos, bbox {x:.3f} x {y:.3f} x {z:.3f} mm".format(
                        tri=int(payload.get("triangles", 0) or 0),
                        pts=int(payload.get("points", 0) or 0),
                        x=float(bbox.get("x", 0.0) or 0.0),
                        y=float(bbox.get("y", 0.0) or 0.0),
                        z=float(bbox.get("z", 0.0) or 0.0),
                    )
                )
        elif kind == "selection_face":
            self.viewer_selection_label.setText(
                "Face: cell {cell}, area {area:.3f} mm2, perimetro {perimeter:.3f} mm".format(
                    cell=int(payload.get("cell_id", -1) or -1),
                    area=float(payload.get("area", 0.0) or 0.0),
                    perimeter=float(payload.get("perimeter", 0.0) or 0.0),
                )
            )
        elif kind == "selection_edge":
            circular = payload.get("circular")
            if isinstance(circular, dict):
                self.viewer_selection_label.setText(
                    "Edge circular: {name}, diametro {diameter:.3f} mm, raio {radius:.3f} mm".format(
                        name=str(circular.get("name", "circulo")),
                        diameter=float(circular.get("diameter", 0.0) or 0.0),
                        radius=float(circular.get("radius", 0.0) or 0.0),
                    )
                )
            else:
                self.viewer_selection_label.setText(
                    "Edge malha: comprimento {length:.3f} mm".format(
                        length=float(payload.get("mesh_segment_length", 0.0) or 0.0)
                    )
                )
        elif kind == "selection_point":
            point = payload.get("point") or (0.0, 0.0, 0.0)
            self.viewer_selection_label.setText(
                "Ponto: ({:.3f}, {:.3f}, {:.3f})".format(float(point[0]), float(point[1]), float(point[2]))
            )
        self._replace_selection_tree(payload)
        self._activity(f"Selecao atualizada: {self.viewer_selection_label.text()}")

    def _handle_measurement_changed(self, payload: dict[str, object]) -> None:
        kind = str(payload.get("type", ""))
        if kind == "edge_measurement":
            circular = payload.get("circular")
            if isinstance(circular, dict):
                self.viewer_measure_label.setText(
                    "Diametro: {diameter:.3f} mm | Raio: {radius:.3f} mm | Circ.: {circ:.3f} mm ({source})".format(
                        diameter=float(circular.get("diameter", 0.0) or 0.0),
                        radius=float(circular.get("radius", 0.0) or 0.0),
                        circ=float(circular.get("circumference", 0.0) or 0.0),
                        source=str(circular.get("source", "metadata")),
                    )
                )
            else:
                self.viewer_measure_label.setText(
                    "Comprimento do edge: {length:.3f} mm".format(
                        length=float(payload.get("mesh_segment_length", 0.0) or 0.0)
                    )
                )
            return
        if kind == "face_measurement":
            self.viewer_measure_label.setText(
                "Face: area {area:.3f} mm2 | perimetro {perimeter:.3f} mm".format(
                    area=float(payload.get("area", 0.0) or 0.0),
                    perimeter=float(payload.get("perimeter", 0.0) or 0.0),
                )
            )
            return
        if kind == "object_measurement":
            bbox = payload.get("bbox") or {}
            if isinstance(bbox, dict):
                x = float(bbox.get("x", 0.0) or 0.0)
                y = float(bbox.get("y", 0.0) or 0.0)
                z = float(bbox.get("z", 0.0) or 0.0)
                self.viewer_measure_label.setText(f"Objeto: bbox {x:.3f} x {y:.3f} x {z:.3f} mm")
            return
        if payload.get("type") == "point":
            point = payload.get("point") or (0.0, 0.0, 0.0)
            normal = payload.get("normal")
            normal_text = ""
            if isinstance(normal, tuple):
                normal_text = " | normal=({:.3f}, {:.3f}, {:.3f})".format(float(normal[0]), float(normal[1]), float(normal[2]))
            self.viewer_measure_label.setText(
                "P1: ({:.3f}, {:.3f}, {:.3f}){}".format(float(point[0]), float(point[1]), float(point[2]), normal_text)
            )
            return
        self.viewer_measure_label.setText(
            "Distancia: {distance:.3f} mm | dX={dx:.3f} dY={dy:.3f} dZ={dz:.3f}".format(
                distance=float(payload.get("distance", 0.0)),
                dx=float(payload.get("dx", 0.0)),
                dy=float(payload.get("dy", 0.0)),
                dz=float(payload.get("dz", 0.0)),
            )
        )

    def _replace_selection_tree(self, payload: dict[str, object]) -> None:
        for index in range(self.object_tree.topLevelItemCount() - 1, -1, -1):
            if self.object_tree.topLevelItem(index).text(0) == "Selecao atual":
                self.object_tree.takeTopLevelItem(index)
        root = QTreeWidgetItem(["Selecao atual", str(payload.get("type", "-"))])
        for key, value in payload.items():
            if key == "type":
                continue
            if isinstance(value, dict):
                child = QTreeWidgetItem([str(key), ""])
                for sub_key, sub_value in value.items():
                    child.addChild(QTreeWidgetItem([str(sub_key), self._short_value(sub_value)]))
                root.addChild(child)
            else:
                root.addChild(QTreeWidgetItem([str(key), self._short_value(value)]))
        self.object_tree.addTopLevelItem(root)
        self.object_tree.expandAll()

    def _short_value(self, value: object) -> str:
        if isinstance(value, float):
            return f"{value:.4f}"
        if isinstance(value, tuple):
            return "(" + ", ".join(f"{float(item):.3f}" if isinstance(item, (int, float)) else str(item) for item in value) + ")"
        return str(value)

    def export_inspection_report(self) -> None:
        if self.inspection_result is None:
            QMessageBox.information(self, "Inspecao CAD", "Nenhuma inspecao disponivel.")
            return
        output_dir = self.current_job_result.job_dir if self.current_job_result else Path(self.output_dir_edit.text()).expanduser()
        md_path, json_path = write_inspection_report(self.inspection_result, output_dir)
        self._activity(f"Relatorio de inspecao: {md_path}")
        self.export_view.appendPlainText(f"\nInspecao:\n{md_path}\n{json_path}")

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
        if not hasattr(self.viewer, "export_png"):
            QMessageBox.warning(self, "PNG", "Viewer atual nao suporta exportacao PNG.")
            return
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
            "viewer_engine_default": "vtk",
            "viewer_fallback": "png/trimesh fallback",
            "inspection_tolerance_mm": self.inspection_tolerance_combo.currentText(),
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
