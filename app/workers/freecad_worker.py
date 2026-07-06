from __future__ import annotations

import json
import os
import shutil
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from app.freecad_runner import FreeCADBinary, discover_freecad_binaries
from app.settings import DIAGNOSTICS_DIR, LOG_DIR, OUTPUT_DIR
from app.workers.process_runner import ProcessResult, ProcessRunner


@dataclass(frozen=True)
class FreeCADJob:
    prompt: str
    macro_path: Path
    output_dir: Path
    export_formats: tuple[str, ...] = ("FCStd", "STEP", "STL", "OBJ", "BREP")
    timeout_sec: int = 120
    job_id: str = ""


@dataclass(frozen=True)
class FreeCADWorkerResult:
    success: bool
    job_id: str
    output_dir: Path
    mode: str
    command: tuple[str, ...]
    returncode: int | None
    elapsed_sec: float
    stdout: str
    stderr: str
    output_paths: dict[str, Path] = field(default_factory=dict)
    error_type: str = ""
    message: str = ""
    suggested_fix: str = ""
    log_file: Path | None = None
    attempts: tuple[dict[str, Any], ...] = ()

    def to_json_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["output_dir"] = str(self.output_dir)
        payload["output_paths"] = {key: str(value) for key, value in self.output_paths.items()}
        payload["log_file"] = str(self.log_file) if self.log_file else None
        return payload


def expected_outputs(macro_path: Path, output_dir: Path) -> dict[str, Path]:
    stem = macro_path.stem
    return {
        "FCStd": output_dir / f"{stem}.FCStd",
        "STEP": output_dir / f"{stem}.step",
        "STL": output_dir / f"{stem}.stl",
        "OBJ": output_dir / f"{stem}.obj",
        "BREP": output_dir / f"{stem}.brep",
        "topology": output_dir / "topology.json",
        "metadata": output_dir / "metadata.json",
        "build_report": output_dir / "build_report.md",
        "prefixed_topology": output_dir / f"{stem}_topology.json",
        "prefixed_metadata": output_dir / f"{stem}_metadata.json",
        "prefixed_build_report": output_dir / f"{stem}_build_report.md",
    }


def created_outputs(macro_path: Path, output_dir: Path) -> dict[str, Path]:
    expected = expected_outputs(macro_path, output_dir)
    created = {kind: path for kind, path in expected.items() if path.exists() and path.stat().st_size > 0}
    if "metadata" not in created and "prefixed_metadata" in created:
        created["metadata"] = created["prefixed_metadata"]
    if "build_report" not in created and "prefixed_build_report" in created:
        created["build_report"] = created["prefixed_build_report"]
    if "topology" not in created and "prefixed_topology" in created:
        created["topology"] = created["prefixed_topology"]
    return created


def build_invocations(binary: FreeCADBinary, macro_path: Path) -> list[tuple[str, list[str]]]:
    path = binary.path
    name = Path(path).name.lower()
    xvfb = shutil.which("xvfb-run")
    invocations: list[tuple[str, list[str]]] = []
    if "freecadcmd" in name:
        invocations.append(("headless_freecadcmd", [path, str(macro_path)]))
    elif binary.is_appimage:
        invocations.append(("appimage_console", [path, "freecadcmd", str(macro_path)]))
        invocations.append(("appimage_console", [path, "--console", str(macro_path)]))
        if xvfb:
            invocations.append(("appimage_xvfb", [xvfb, "-a", path, "--console", str(macro_path)]))
    else:
        invocations.append(("headless_freecad_gui_console", [path, "--console", str(macro_path)]))
        invocations.append(("headless_freecad_gui_console", [path, "-c", str(macro_path)]))
        if xvfb:
            invocations.append(("headless_freecad_gui_console", [xvfb, "-a", path, "--console", str(macro_path)]))
    return invocations


class FreeCADWorker:
    _minimal_result: FreeCADWorkerResult | None = None

    def __init__(self, logs_dir: Path = LOG_DIR) -> None:
        self.logs_dir = logs_dir
        self.logs_dir.mkdir(parents=True, exist_ok=True)

    def run(self, job: FreeCADJob, on_line=None) -> FreeCADWorkerResult:
        macro_path = job.macro_path.expanduser().resolve()
        output_dir = job.output_dir.expanduser().resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        if not macro_path.exists():
            return self._failure(job, "macro_error", f"Macro nao encontrada: {macro_path}", "Gere a macro novamente antes de executar.")

        binaries = discover_freecad_binaries()
        if not binaries:
            return self._failure(job, "freecad_not_found", "FreeCAD nao encontrado.", "Instale FreeCAD ou defina FREECAD_CMD.")

        minimal = self.run_minimal_test(on_line=on_line)
        if not minimal.success:
            payload = FreeCADWorkerResult(
                success=False,
                job_id=job.job_id,
                output_dir=output_dir,
                mode=minimal.mode,
                command=minimal.command,
                returncode=minimal.returncode,
                elapsed_sec=minimal.elapsed_sec,
                stdout=minimal.stdout,
                stderr=minimal.stderr,
                output_paths=minimal.output_paths,
                error_type="freecad_environment_failed",
                message="FreeCAD nao passou no teste minimo. O problema esta no ambiente/executor, nao na macro.",
                suggested_fix="Veja o log do teste minimo e confirme FreeCAD, Mesh e Part.export.",
                log_file=minimal.log_file,
                attempts=minimal.attempts,
            )
            self._write_runtime_report(payload)
            return payload

        env = os.environ.copy()
        env["PROMPT_FORGE_OUTPUT"] = str(output_dir)
        env.setdefault("QT_QPA_PLATFORM", "offscreen")
        attempts: list[dict[str, Any]] = []
        last_result: ProcessResult | None = None
        last_mode = ""
        for binary in binaries:
            for mode, command in build_invocations(binary, macro_path):
                log_file = self.logs_dir / f"freecad_{job.job_id or macro_path.stem}_{datetime.now().strftime('%H%M%S')}_{mode}.log"
                result = ProcessRunner.run(
                    command=command,
                    timeout_sec=job.timeout_sec,
                    cwd=output_dir,
                    env=env,
                    log_file=log_file,
                    on_line=on_line,
                )
                last_result = result
                last_mode = mode
                attempt = {
                    "mode": mode,
                    "command": command,
                    "returncode": result.returncode,
                    "elapsed_sec": result.elapsed_sec,
                    "timed_out": result.timed_out,
                    "log_file": str(result.log_file) if result.log_file else None,
                }
                attempts.append(attempt)
                created = created_outputs(macro_path, output_dir)
                required = {"FCStd", "STEP", "STL", "OBJ", "metadata", "build_report", "topology"}
                if result.ok and required.issubset(created):
                    payload = FreeCADWorkerResult(
                        success=True,
                        job_id=job.job_id,
                        output_dir=output_dir,
                        mode=mode,
                        command=tuple(command),
                        returncode=result.returncode,
                        elapsed_sec=result.elapsed_sec,
                        stdout=result.stdout,
                        stderr=result.stderr,
                        output_paths=created,
                        message="FreeCAD executou em subprocesso headless e gerou os arquivos esperados.",
                        log_file=result.log_file,
                        attempts=tuple(attempts),
                    )
                    self._write_runtime_report(payload)
                    return payload
                if result.timed_out:
                    break

        assert last_result is not None
        created = created_outputs(macro_path, output_dir)
        error_type = self._classify_failure(last_result, created)
        payload = FreeCADWorkerResult(
            success=False,
            job_id=job.job_id,
            output_dir=output_dir,
            mode=last_mode,
            command=last_result.command,
            returncode=last_result.returncode,
            elapsed_sec=last_result.elapsed_sec,
            stdout=last_result.stdout,
            stderr=last_result.stderr,
            output_paths=created,
            error_type=error_type,
            message=self._message_for(error_type, created),
            suggested_fix=self._suggested_fix(error_type),
            log_file=last_result.log_file,
            attempts=tuple(attempts),
        )
        self._write_runtime_report(payload)
        return payload

    def run_minimal_test(self, force: bool = False, on_line=None) -> FreeCADWorkerResult:
        if FreeCADWorker._minimal_result is not None and FreeCADWorker._minimal_result.success and not force:
            if on_line:
                on_line("runner", "Teste minimo FreeCAD ja passou nesta sessao.\n")
            return FreeCADWorker._minimal_result

        output_dir = OUTPUT_DIR / "diagnostics"
        output_dir.mkdir(parents=True, exist_ok=True)
        macro_path = DIAGNOSTICS_DIR / "freecad_minimal_test.py"
        macro_path.parent.mkdir(parents=True, exist_ok=True)
        macro_path.write_text(
            "\n".join(
                [
                    "import FreeCAD as App",
                    "import Part",
                    "import Mesh",
                    "import os",
                    "",
                    f"out = {str(output_dir)!r}",
                    "os.makedirs(out, exist_ok=True)",
                    "doc = App.newDocument('MinimalTest')",
                    "shape = Part.makeCylinder(10, 5)",
                    "obj = doc.addObject('Part::Feature', 'Cylinder')",
                    "obj.Shape = shape",
                    "doc.recompute()",
                    "doc.saveAs(os.path.join(out, 'minimal_test.FCStd'))",
                    "Part.export([obj], os.path.join(out, 'minimal_test.step'))",
                    "Mesh.export([obj], os.path.join(out, 'minimal_test.stl'))",
                    "print('FREECAD_MINIMAL_TEST_OK')",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        binaries = discover_freecad_binaries()
        if not binaries:
            result = FreeCADWorkerResult(
                success=False,
                job_id="freecad_minimal_test",
                output_dir=output_dir,
                mode="not_started",
                command=(),
                returncode=None,
                elapsed_sec=0.0,
                stdout="",
                stderr="",
                error_type="freecad_not_found",
                message="FreeCAD nao encontrado.",
                suggested_fix="Instale FreeCAD ou defina FREECAD_CMD.",
            )
            FreeCADWorker._minimal_result = result
            return result

        env = os.environ.copy()
        env["PROMPT_FORGE_OUTPUT"] = str(output_dir)
        env.setdefault("QT_QPA_PLATFORM", "offscreen")
        attempts: list[dict[str, Any]] = []
        last_result: ProcessResult | None = None
        last_mode = ""
        expected = {
            "FCStd": output_dir / "minimal_test.FCStd",
            "STEP": output_dir / "minimal_test.step",
            "STL": output_dir / "minimal_test.stl",
        }
        for path in expected.values():
            try:
                path.unlink()
            except FileNotFoundError:
                pass
        for binary in binaries:
            for mode, command in build_invocations(binary, macro_path):
                log_file = self.logs_dir / f"freecad_minimal_test_{datetime.now().strftime('%H%M%S')}_{mode}.log"
                result = ProcessRunner.run(
                    command=command,
                    timeout_sec=30,
                    cwd=output_dir,
                    env=env,
                    log_file=log_file,
                    on_line=on_line,
                )
                last_result = result
                last_mode = mode
                attempts.append(
                    {
                        "mode": mode,
                        "command": command,
                        "returncode": result.returncode,
                        "elapsed_sec": result.elapsed_sec,
                        "timed_out": result.timed_out,
                        "log_file": str(result.log_file) if result.log_file else None,
                    }
                )
                created = {kind: path for kind, path in expected.items() if path.exists() and path.stat().st_size > 0}
                if result.ok and set(expected).issubset(created) and "FREECAD_MINIMAL_TEST_OK" in result.stdout:
                    payload = FreeCADWorkerResult(
                        success=True,
                        job_id="freecad_minimal_test",
                        output_dir=output_dir,
                        mode=mode,
                        command=tuple(command),
                        returncode=result.returncode,
                        elapsed_sec=result.elapsed_sec,
                        stdout=result.stdout,
                        stderr=result.stderr,
                        output_paths=created,
                        message="FreeCAD OK: teste minimo gerou FCStd, STEP e STL.",
                        log_file=result.log_file,
                        attempts=tuple(attempts),
                    )
                    self._write_runtime_report(payload)
                    FreeCADWorker._minimal_result = payload
                    return payload
                if result.timed_out:
                    break

        assert last_result is not None
        payload = FreeCADWorkerResult(
            success=False,
            job_id="freecad_minimal_test",
            output_dir=output_dir,
            mode=last_mode,
            command=last_result.command,
            returncode=last_result.returncode,
            elapsed_sec=last_result.elapsed_sec,
            stdout=last_result.stdout,
            stderr=last_result.stderr,
            output_paths={kind: path for kind, path in expected.items() if path.exists() and path.stat().st_size > 0},
            error_type=self._classify_failure(last_result, {}),
            message="FreeCAD nao passou no teste minimo.",
            suggested_fix="Corrija o ambiente FreeCAD antes de executar macros de usuario.",
            log_file=last_result.log_file,
            attempts=tuple(attempts),
        )
        self._write_runtime_report(payload)
        FreeCADWorker._minimal_result = payload
        return payload

    def _failure(self, job: FreeCADJob, error_type: str, message: str, suggested_fix: str) -> FreeCADWorkerResult:
        payload = FreeCADWorkerResult(
            success=False,
            job_id=job.job_id,
            output_dir=job.output_dir,
            mode="not_started",
            command=(),
            returncode=None,
            elapsed_sec=0.0,
            stdout="",
            stderr="",
            error_type=error_type,
            message=message,
            suggested_fix=suggested_fix,
        )
        self._write_runtime_report(payload)
        return payload

    def _classify_failure(self, result: ProcessResult, outputs: dict[str, Path]) -> str:
        text = (result.stdout + "\n" + result.stderr).lower()
        if result.timed_out:
            return "timeout"
        if "traceback" in text or "syntaxerror" in text or "nameerror" in text:
            return "macro_error"
        if "invalid" in text or "shape" in text and "not valid" in text:
            return "shape_invalid"
        if outputs and {"FCStd", "STEP", "STL", "OBJ"}.difference(outputs):
            return "export_error"
        return "export_error" if result.returncode == 0 else "macro_error"

    def _message_for(self, error_type: str, outputs: dict[str, Path]) -> str:
        if error_type == "timeout":
            return "Timeout: FreeCAD excedeu o tempo limite; processo foi encerrado."
        if error_type == "macro_error":
            return "FreeCAD retornou erro ao executar a macro."
        if error_type == "shape_invalid":
            return "A geometria foi gerada, mas a validacao do shape falhou."
        if error_type == "export_error":
            missing = sorted({"FCStd", "STEP", "STL", "OBJ", "metadata", "build_report"}.difference(outputs))
            return "Exportacao incompleta. Ausentes: " + ", ".join(missing)
        return "Falha desconhecida na execucao FreeCAD."

    def _suggested_fix(self, error_type: str) -> str:
        return {
            "timeout": "Reduza complexidade da peca ou aumente timeout_sec.",
            "macro_error": "Abra o log bruto e revise traceback da macro.",
            "shape_invalid": "Simplifique booleanos ou aumente tolerancia de reparo.",
            "export_error": "Confirme permissoes da pasta do job e veja stdout/stderr do FreeCAD.",
            "freecad_not_found": "Instale FreeCAD ou defina FREECAD_CMD.",
        }.get(error_type, "Rode make doctor e envie o relatorio.")

    def _write_runtime_report(self, payload: FreeCADWorkerResult) -> None:
        report = payload.output_dir / "runtime_report.json"
        report.write_text(json.dumps(payload.to_json_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
