from __future__ import annotations

import importlib
import json
import os
import platform
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app.freecad_runner import (
    discover_freecad_binaries,
    get_freecad_version,
    run_macro,
    write_execution_report,
)
from app.importers.dwg_importer import detect_converters
from app.macro_generator import MacroGenerator
from app.prompt_parser import parse_prompt
from app.diagnostics.freeze_detector import run_freeze_diagnostics
from app.rag_index_v2 import V2_AUDIT_FILE, V2_CHUNKS_FILE
from app.settings import APP_DIR, DIAGNOSTICS_DIR, MACROS_DIR, OUTPUT_DIR, RAG_DIR


@dataclass(frozen=True)
class DoctorCheck:
    name: str
    status: str
    message: str

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    @property
    def failed(self) -> bool:
        return self.status == "fail"


def _check_import(module: str) -> DoctorCheck:
    try:
        imported = importlib.import_module(module)
        version = getattr(imported, "__version__", "")
        return DoctorCheck(module, "ok", f"importavel{f' ({version})' if version else ''}")
    except Exception as exc:
        return DoctorCheck(module, "fail", str(exc))


def _count_chunks(path: Path) -> int:
    if not path.exists():
        return 0
    try:
        return len(json.loads(path.read_text(encoding="utf-8")))
    except Exception:
        return 0


def _check_ui_open() -> DoctorCheck:
    previous_platform = os.environ.get("QT_QPA_PLATFORM")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        from PySide6.QtWidgets import QApplication

        from app.ui_main import MainWindow

        app = QApplication.instance() or QApplication([])
        window = MainWindow()
        window.resize(900, 600)
        app.processEvents()
        window.close()
        if previous_platform is not None:
            os.environ["QT_QPA_PLATFORM"] = previous_platform
        return DoctorCheck("ui_open", "ok", "MainWindow instanciada com plataforma Qt offscreen")
    except Exception as exc:
        if previous_platform is not None:
            os.environ["QT_QPA_PLATFORM"] = previous_platform
        return DoctorCheck("ui_open", "fail", str(exc))


def _generate_and_run_probe() -> tuple[DoctorCheck, DoctorCheck, DoctorCheck, DoctorCheck, Path | None]:
    try:
        spec = parse_prompt("placa de aluminio 40x30x4 mm com quatro furos de 4 mm nos cantos")
        design = MacroGenerator(use_deepseek=False).generate(spec)
        generate_check = DoctorCheck("generate_macro", "ok", str(design.macro_path))
    except Exception as exc:
        return (
            DoctorCheck("generate_macro", "fail", str(exc)),
            DoctorCheck("execute_macro", "fail", "macro nao foi gerada"),
            DoctorCheck("export_step", "fail", "macro nao foi gerada"),
            DoctorCheck("export_stl", "fail", "macro nao foi gerada"),
            None,
        )
    result = run_macro(design.macro_path, OUTPUT_DIR, timeout=180)
    write_execution_report(
        result,
        design.macro_path,
        solution="Doctor gerou e executou uma placa de prova sem usar DeepSeek." if result.ok else "Revise as tentativas registradas; o backend FreeCAD nao exportou todos os arquivos esperados.",
    )
    execute_check = DoctorCheck("execute_macro", "ok" if result.ok else "fail", result.message)
    step_check = DoctorCheck(
        "export_step",
        "ok" if any(path.suffix.lower() == ".step" for path in result.output_paths.values()) else "fail",
        str(result.output_paths.get("STEP", "STEP nao confirmado")),
    )
    stl_check = DoctorCheck(
        "export_stl",
        "ok" if any(path.suffix.lower() == ".stl" for path in result.output_paths.values()) else "fail",
        str(result.output_paths.get("STL", "STL nao confirmado")),
    )
    return generate_check, execute_check, step_check, stl_check, design.macro_path


def run_doctor(run_probe: bool = True, run_ui: bool = True) -> dict[str, object]:
    DIAGNOSTICS_DIR.mkdir(parents=True, exist_ok=True)
    checks: list[DoctorCheck] = []

    checks.append(DoctorCheck("python", "ok", f"{sys.version.split()[0]} ({platform.python_implementation()})"))
    checks.append(DoctorCheck("venv", "ok" if sys.prefix != sys.base_prefix else "warn", sys.prefix))
    checks.append(_check_import("PySide6"))
    checks.append(_check_import("numpy"))
    checks.append(_check_import("sklearn"))

    binaries = discover_freecad_binaries()
    checks.append(DoctorCheck("freecad_binary", "ok" if binaries else "fail", binaries[0].path if binaries else "nenhum binario FreeCAD encontrado"))
    checks.append(DoctorCheck("freecadcmd", "ok" if any("freecadcmd" in Path(item.path).name.lower() for item in binaries) else "warn", "freecadcmd direto no PATH nao encontrado; AppImage console sera usado" if binaries else "ausente"))
    checks.append(DoctorCheck("freecad_version", "ok" if binaries else "fail", get_freecad_version(binaries[0].path) if binaries else "nao detectada"))
    appimages = [item.path for item in binaries if item.is_appimage]
    checks.append(DoctorCheck("appimage", "ok" if appimages else "warn", appimages[0] if appimages else "nenhum AppImage detectado"))
    checks.append(DoctorCheck("xvfb", "ok" if shutil.which("xvfb-run") else "warn", shutil.which("xvfb-run") or "instale com: sudo apt install xvfb"))
    checks.append(DoctorCheck("fuse", "ok" if Path("/dev/fuse").exists() else "warn", "/dev/fuse disponivel" if Path("/dev/fuse").exists() else "FUSE nao visivel; AppImage ainda pode funcionar por fallback proprio"))

    for directory in (APP_DIR, MACROS_DIR, OUTPUT_DIR, RAG_DIR, DIAGNOSTICS_DIR):
        checks.append(DoctorCheck(f"writable:{directory.name}", "ok" if os.access(directory, os.W_OK) else "fail", str(directory)))

    chunk_count = _count_chunks(V2_CHUNKS_FILE)
    checks.append(DoctorCheck("rag_chunks_v2", "ok" if chunk_count >= 25_000 else "warn", f"{chunk_count} chunks em {V2_CHUNKS_FILE}"))
    if V2_AUDIT_FILE.exists():
        checks.append(DoctorCheck("rag_audit_file", "ok", str(V2_AUDIT_FILE)))
    else:
        checks.append(DoctorCheck("rag_audit_file", "warn", "rode make ingest para gerar auditoria"))

    viewer_checks = [_check_import("trimesh"), _check_import("app.viewer3d.fallback_viewer")]
    checks.extend(DoctorCheck(f"viewer:{item.name}", item.status, item.message) for item in viewer_checks)
    checks.append(_check_import("ezdxf"))
    checks.append(_check_import("svgpathtools"))

    converters = detect_converters()
    found_converters = {name: path for name, path in converters.items() if path}
    checks.append(
        DoctorCheck(
            "dwg_converters",
            "ok" if found_converters else "warn",
            ", ".join(f"{name}={path}" for name, path in found_converters.items()) or "nenhum conversor DWG; instale LibreDWG, ODA/Teigha File Converter ou QCAD Pro",
        )
    )

    generated_macro: Path | None = None
    if run_probe:
        generate_check, execute_check, step_check, stl_check, generated_macro = _generate_and_run_probe()
        checks.extend([generate_check, execute_check, step_check, stl_check])
    try:
        freeze = run_freeze_diagnostics()
        checks.append(
            DoctorCheck(
                "freeze_detector",
                "ok" if int(freeze.get("high", 0)) == 0 else "fail",
                f"{freeze.get('total_findings', 0)} findings; high={freeze.get('high', 0)}; report=data/diagnostics/freeze_report.md",
            )
        )
    except Exception as exc:
        checks.append(DoctorCheck("freeze_detector", "warn", str(exc)))
    if run_ui:
        checks.append(_check_ui_open())

    payload = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "project": str(APP_DIR),
        "freecad_binaries": [item.__dict__ for item in binaries],
        "generated_macro": str(generated_macro) if generated_macro else None,
        "checks": [check.__dict__ for check in checks],
        "failed": [check.__dict__ for check in checks if check.failed],
        "warnings": [check.__dict__ for check in checks if check.status == "warn"],
    }
    _write_report(payload)
    return payload


def _write_report(payload: dict[str, object]) -> Path:
    checks = [DoctorCheck(**item) for item in payload["checks"]]  # type: ignore[arg-type]
    lines = [
        "# Doctor Report",
        "",
        f"- Criado em: `{payload['created_at']}`",
        f"- Projeto: `{payload['project']}`",
        f"- Falhas: `{len(payload['failed'])}`",
        f"- Avisos: `{len(payload['warnings'])}`",
        "",
        "## Checks",
        "",
        "| Status | Check | Mensagem |",
        "| --- | --- | --- |",
    ]
    for check in checks:
        lines.append(f"| {check.status} | {check.name} | {check.message.replace('|', '/')} |")
    lines.extend(
        [
            "",
            "## Binarios FreeCAD",
            "```json",
            json.dumps(payload["freecad_binaries"], ensure_ascii=False, indent=2),
            "```",
            "",
        ]
    )
    report_path = DIAGNOSTICS_DIR / "doctor_report.md"
    report_path.write_text("\n".join(lines), encoding="utf-8")
    (DIAGNOSTICS_DIR / "doctor_report.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return report_path


def main() -> int:
    payload = run_doctor()
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 1 if payload["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
