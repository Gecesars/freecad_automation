from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.agent import PromptAgent
from app.freecad_runner import find_freecad_executable, run_macro
from app.job_manager import JobManager
from app.rag_store import LocalRagStore
from app.settings import LOG_DIR, OUTPUT_DIR
from app.workers.viewer_worker import ViewerWorker


STYLE = """
QWidget {
    color: #172333;
    font-size: 13px;
}
QMainWindow { background: #f4f6f8; color: #172333; }
QToolBar {
    background: #eef1f5;
    border-bottom: 1px solid #c9d0d8;
    spacing: 6px;
    padding: 4px;
}
QToolBar QToolButton {
    color: #172333;
    background: transparent;
    padding: 4px;
}
QLabel {
    color: #172333;
}
QLabel#PanelTitle {
    color: #132033;
    font-size: 15px;
    font-weight: 700;
}
QLabel#ActivityLabel {
    color: #063f77;
    font-weight: 700;
}
QPlainTextEdit, QLineEdit {
    background: #ffffff;
    border: 1px solid #c8d0da;
    border-radius: 4px;
    padding: 6px;
    color: #111827;
    selection-background-color: #2666a3;
    selection-color: #ffffff;
}
QPlainTextEdit#PromptInput {
    color: #0b1220;
    background: #ffffff;
    font-size: 14px;
    font-weight: 600;
}
QPlainTextEdit#ActivityLog {
    background: #ffffff;
    color: #111827;
    font-size: 12px;
}
QPushButton {
    background: #ffffff;
    border: 1px solid #b9c2ce;
    border-radius: 4px;
    padding: 6px 10px;
    color: #132033;
}
QPushButton:hover {
    background: #edf6ff;
    border-color: #6aa2d8;
}
QPushButton:pressed { background: #d9ebfb; }
QPushButton:disabled {
    color: #485465;
    background: #eef1f4;
}
QGroupBox {
    border: 1px solid #c8d0da;
    border-radius: 4px;
    margin-top: 12px;
    padding: 8px;
    color: #172333;
    font-weight: 700;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 8px;
    padding: 0 4px;
    background: #f4f6f8;
    color: #132033;
}
QComboBox, QDoubleSpinBox, QTreeWidget {
    background: #ffffff;
    border: 1px solid #c8d0da;
    color: #111827;
    selection-background-color: #2666a3;
    selection-color: #ffffff;
}
QComboBox QAbstractItemView, QAbstractItemView {
    background: #ffffff;
    color: #111827;
    border: 1px solid #9aa7b7;
    selection-background-color: #2666a3;
    selection-color: #ffffff;
    outline: 0;
}
QTreeWidget::item {
    color: #111827;
    background: #ffffff;
    padding: 2px;
}
QTreeWidget::item:selected {
    color: #ffffff;
    background: #2666a3;
}
QMenu {
    background: #ffffff;
    color: #111827;
    border: 1px solid #8fa0b3;
    padding: 4px;
}
QMenu::item {
    background: transparent;
    color: #111827;
    padding: 6px 30px 6px 24px;
}
QMenu::item:selected {
    background: #2666a3;
    color: #ffffff;
}
QMenu::item:disabled {
    color: #6b7280;
}
QMenu::separator {
    height: 1px;
    background: #c8d0da;
    margin: 5px 8px;
}
QCheckBox { color: #172333; spacing: 5px; }
QCheckBox::indicator {
    width: 14px;
    height: 14px;
    border: 1px solid #5f6b7a;
    background: #ffffff;
}
QCheckBox::indicator:checked {
    background: #1f6fb2;
    border: 1px solid #155a94;
}
QCheckBox::indicator:disabled {
    background: #d8dde5;
    border: 1px solid #9aa7b7;
}
QToolTip {
    background: #111827;
    color: #ffffff;
    border: 1px solid #374151;
    padding: 4px;
}
QTabWidget::pane {
    border: 1px solid #c8d0da;
    background: #ffffff;
}
QTabBar::tab {
    background: #dfe7ef;
    border: 1px solid #c8d0da;
    padding: 7px 12px;
    margin-right: 2px;
    color: #263445;
}
QTabBar::tab:selected {
    background: #ffffff;
    border-bottom-color: #ffffff;
    color: #0f1f33;
    font-weight: 700;
}
QTabBar::tab:hover {
    background: #edf6ff;
    color: #0f1f33;
}
QProgressBar {
    border: 1px solid #b9c2ce;
    border-radius: 4px;
    background: #ffffff;
    color: #172333;
    text-align: center;
}
QProgressBar::chunk {
    background: #2b7cc4;
}
QStatusBar {
    background: #eef1f5;
    border-top: 1px solid #c9d0d8;
    color: #172333;
}
"""


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="FreeCAD Prompt Forge")
    parser.add_argument("--prompt", help="Descricao textual da peca a gerar.")
    parser.add_argument("--generate-only", action="store_true", help="Gera apenas a macro Python.")
    parser.add_argument("--run-freecad", action="store_true", help="Gera e executa a macro no FreeCAD.")
    parser.add_argument("--view", action="store_true", help="Prepara visualizacao por STL/OBJ ou fallback PNG apos executar.")
    parser.add_argument("--output-dir", default=str(OUTPUT_DIR), help="Pasta para FCStd/STEP/STL.")
    parser.add_argument("--json", action="store_true", help="Imprime resultado estruturado em JSON.")
    return parser.parse_args(argv)


def run_cli(args: argparse.Namespace) -> int:
    output_dir = Path(args.output_dir).expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)
    status_lines: list[str] = []

    def on_status(message: str) -> None:
        status_lines.append(message)
        print(f"[job] {message}", flush=True)

    viewer_payload = None
    if args.run_freecad or args.view:
        job_result = JobManager(LocalRagStore()).run_prompt(args.prompt, run_freecad=True, on_status=on_status)
        design = job_result.design
        run_result = job_result.freecad
        if args.view and run_result and run_result.success:
            mesh_path = run_result.output_paths.get("STL") or run_result.output_paths.get("OBJ")
            if mesh_path:
                viewer_result = ViewerWorker().prepare(mesh_path, job_result.job_dir)
                topology_path = None
                if run_result:
                    topology_path = run_result.output_paths.get("topology") or run_result.output_paths.get("prefixed_topology")
                viewer_payload = {
                    "ok": viewer_result.ok,
                    "mode": viewer_result.viewer_mode,
                    "message": viewer_result.message,
                    "mesh_path": str(viewer_result.mesh_path) if viewer_result.mesh_path else None,
                    "display_mesh_path": str(viewer_result.display_mesh_path) if viewer_result.display_mesh_path else None,
                    "topology_path": str(topology_path) if topology_path else None,
                    "topology_available": bool(topology_path and topology_path.exists()),
                    "preview_images": {key: str(value) for key, value in viewer_result.preview_images.items()},
                    "bbox": viewer_result.bbox,
                    "faces": viewer_result.face_count,
                    "vertices": viewer_result.vertex_count,
                    "original_faces": viewer_result.original_face_count,
                    "original_vertices": viewer_result.original_vertex_count,
                    "lod_mode": viewer_result.lod_mode,
                    "load_seconds": viewer_result.load_seconds,
                    "error": viewer_result.error,
                }
                print(f"[viewer] {viewer_result.message}", flush=True)
    else:
        agent = PromptAgent(LocalRagStore(), output_dir=output_dir)
        design = agent.generate(args.prompt)
        run_result = None

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / "last_cli.log"
    log_lines = [
        f"Prompt: {args.prompt}",
        f"Macro: {design.macro_path}",
        f"FreeCAD: {find_freecad_executable() or 'nao encontrado'}",
    ]
    if run_result:
        run_ok = run_result.success if hasattr(run_result, "success") else run_result.ok
        run_message = run_result.message
        run_command = run_result.command
        run_stdout = run_result.stdout
        run_stderr = run_result.stderr
        log_lines.extend(
            [
                f"Run ok: {run_ok}",
                f"Message: {run_message}",
                f"Command: {' '.join(run_command) if run_command else '(nenhum)'}",
                "STDOUT:",
                run_stdout,
                "STDERR:",
                run_stderr,
            ]
        )
    log_path.write_text("\n".join(log_lines), encoding="utf-8")

    payload = {
        "macro_path": str(design.macro_path),
        "expected_outputs": {kind: str(path) for kind, path in design.output_paths.items()},
        "spec": design.spec.to_dict(),
        "rag_results": [
            {
                "title": item.title,
                "url": item.url,
                "score": item.score,
                "source_file": item.source_file,
                "chunk_index": item.chunk_index,
            }
            for item in design.rag_results
        ],
        "freecad": {
            "detected": find_freecad_executable(),
            "run": None
            if run_result is None
            else {
                "ok": run_result.success if hasattr(run_result, "success") else run_result.ok,
                "message": run_result.message,
                "outputs": {kind: str(path) for kind, path in run_result.output_paths.items()},
                "mode": run_result.mode,
                "elapsed_sec": getattr(run_result, "elapsed_sec", None),
            },
        },
        "viewer": viewer_payload,
        "status": status_lines,
        "deepseek": {
            "used": design.llm_used,
            "model": design.llm_model,
            "notes": design.llm_notes,
        },
        "log_path": str(log_path),
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(design.summary)
        if run_result:
            print()
            print(run_result.message)
            for kind, path in run_result.output_paths.items():
                print(f"{kind}: {path}")
        if viewer_payload:
            print()
            print(f"Viewer: {viewer_payload['mode']} ok={viewer_payload['ok']}")
            for key, path in viewer_payload["preview_images"].items():
                print(f"preview_{key}: {path}")
        print(f"Log: {log_path}")
    return 0


def run_gui() -> int:
    from PySide6.QtWidgets import QApplication

    from app.ui_main import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName("FreeCAD Prompt Forge")
    app.setStyleSheet(STYLE)
    window = MainWindow()
    window.showMaximized()
    return app.exec()


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.prompt:
        if not args.generate_only and not args.run_freecad:
            args.generate_only = True
        return run_cli(args)
    return run_gui()


if __name__ == "__main__":
    raise SystemExit(main())
