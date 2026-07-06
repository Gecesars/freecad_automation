from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from app.models import RunResult
from app.settings import DEFAULT_FREECAD_CANDIDATES, DIAGNOSTICS_DIR, OUTPUT_DIR


@dataclass(frozen=True)
class FreeCADBinary:
    path: str
    source: str
    is_appimage: bool


def _is_appimage(command: str) -> bool:
    path = Path(command)
    if path.suffix.lower() == ".appimage":
        return True
    try:
        return path.resolve().suffix.lower() == ".appimage"
    except OSError:
        return False


def _candidate_paths() -> list[tuple[str, str]]:
    candidates: list[tuple[str, str]] = [
        ("freecadcmd", "PATH freecadcmd"),
        ("FreeCADCmd", "PATH FreeCADCmd"),
        ("freecad", "PATH freecad"),
        ("FreeCAD", "PATH FreeCAD"),
        (str(Path.home() / "bin" / "freecad"), "local wrapper"),
    ]
    candidates.extend((str(path), "home AppImage") for path in sorted((Path.home() / "Applications").glob("*FreeCAD*.AppImage")))
    candidates.extend((str(path), "opt AppImage") for path in sorted(Path("/opt").glob("**/*FreeCAD*.AppImage"))[:50])
    candidates.extend((str(path), "project AppImage") for path in sorted(Path.cwd().glob("**/*FreeCAD*.AppImage"))[:20])
    extracted_patterns = [
        Path.home() / "Applications" / "squashfs-root" / "usr" / "bin",
        Path.cwd() / "squashfs-root" / "usr" / "bin",
    ]
    for base in extracted_patterns:
        candidates.extend((str(base / name), "extracted AppImage") for name in ("freecadcmd", "FreeCADCmd", "freecad", "FreeCAD"))
    candidates.extend((item, "configured candidate") for item in DEFAULT_FREECAD_CANDIDATES)
    env_value = os.environ.get("FREECAD_CMD")
    if env_value:
        candidates.insert(0, (env_value, "FREECAD_CMD"))
    deduped: list[tuple[str, str]] = []
    seen: set[str] = set()
    for candidate, source in candidates:
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        deduped.append((candidate, source))
    return deduped


def discover_freecad_binaries() -> list[FreeCADBinary]:
    found: list[FreeCADBinary] = []
    seen_real: set[str] = set()
    for candidate, source in _candidate_paths():
        resolved = shutil.which(candidate)
        path = Path(resolved or candidate).expanduser()
        if not path.exists() or not os.access(path, os.X_OK):
            continue
        try:
            real = str(path.resolve())
        except OSError:
            real = str(path)
        key = real if real else str(path)
        if key in seen_real:
            continue
        seen_real.add(key)
        found.append(FreeCADBinary(path=str(path), source=source, is_appimage=_is_appimage(str(path))))
    return found


def find_freecad_executable() -> str | None:
    binaries = discover_freecad_binaries()
    return binaries[0].path if binaries else None


def get_freecad_version(command: str | None = None, timeout: int = 20) -> str:
    command = command or find_freecad_executable()
    if not command:
        return "FreeCAD nao encontrado"
    attempts = [[command, "freecadcmd", "--version"], [command, "--version"], [command, "-v"]]
    for invocation in attempts:
        try:
            proc = subprocess.run(invocation, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout, check=False)
        except Exception:
            continue
        text = (proc.stdout + "\n" + proc.stderr).strip()
        if text:
            return text.splitlines()[0]
    return "Versao nao detectada"


def _xvfb_run() -> str | None:
    return shutil.which("xvfb-run")


def _invocations_for(binary: FreeCADBinary, script_path: Path, include_gui: bool = False) -> list[tuple[str, list[str]]]:
    script = str(script_path)
    path = binary.path
    name = Path(path).name.lower()
    invocations: list[tuple[str, list[str]]] = []
    if "freecadcmd" in name:
        invocations.append(("headless_freecadcmd", [path, script]))
    elif binary.is_appimage:
        invocations.append(("appimage_console", [path, "freecadcmd", script]))
        invocations.append(("appimage_console", [path, "--console", script]))
        if _xvfb_run():
            invocations.append(("appimage_xvfb", [_xvfb_run() or "xvfb-run", "-a", path, "--console", script]))
    else:
        invocations.append(("headless_freecad_gui_console", [path, "-c", script]))
        invocations.append(("headless_freecad_gui_console", [path, "--console", script]))
        if _xvfb_run():
            invocations.append(("headless_freecad_gui_console", [_xvfb_run() or "xvfb-run", "-a", path, "--console", script]))
    if include_gui:
        invocations.append(("gui_interactive", [path, script]))
    return invocations


def _expected_outputs(script_path: Path, output_dir: Path) -> dict[str, Path]:
    stem = script_path.stem
    return {
        "FCStd": output_dir / f"{stem}.FCStd",
        "STEP": output_dir / f"{stem}.step",
        "STL": output_dir / f"{stem}.stl",
        "BREP": output_dir / f"{stem}.brep",
        "OBJ": output_dir / f"{stem}.obj",
        "metadata": output_dir / f"{stem}_metadata.json",
        "build_report": output_dir / f"{stem}_build_report.md",
        "thumbnail": output_dir / f"{stem}_thumbnail.png",
    }


def _created_outputs(expected: dict[str, Path], output_dir: Path) -> dict[str, Path]:
    return {kind: path for kind, path in expected.items() if path.exists()}


def _run_invocation(
    mode: str,
    invocation: list[str],
    output_dir: Path,
    timeout: int,
    env: dict[str, str],
) -> dict[str, object]:
    try:
        proc = subprocess.run(
            invocation,
            cwd=str(output_dir),
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
        return {
            "mode": mode,
            "command": invocation,
            "returncode": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "timeout": False,
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "mode": mode,
            "command": invocation,
            "returncode": None,
            "stdout": exc.stdout or "",
            "stderr": exc.stderr or "",
            "timeout": True,
        }


def run_macro(
    script_path: Path,
    output_dir: Path = OUTPUT_DIR,
    timeout: int = 180,
    include_gui: bool = False,
    dry_run: bool = False,
) -> RunResult:
    script_path = script_path.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    expected = _expected_outputs(script_path, output_dir)
    if dry_run:
        return RunResult(
            ok=script_path.exists(),
            command=(),
            returncode=0 if script_path.exists() else 1,
            stdout="Dry run: macro not executed.",
            stderr="",
            message="Dry run concluido.",
            mode="dry_run",
            output_paths={},
            attempts=(),
        )

    env = os.environ.copy()
    env["PROMPT_FORGE_OUTPUT"] = str(output_dir)
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    attempts: list[dict[str, object]] = []
    embedded_python = env.get("FREECAD_PYTHON", "").strip()
    if embedded_python:
        embedded_path = Path(embedded_python).expanduser()
        if embedded_path.exists() and os.access(embedded_path, os.X_OK):
            attempt = _run_invocation("python_embedded", [str(embedded_path), str(script_path)], output_dir, timeout, env)
            attempts.append(attempt)
            created = _created_outputs(expected, output_dir)
            if attempt["returncode"] == 0 and created:
                return RunResult(
                    ok=True,
                    command=(str(embedded_path), str(script_path)),
                    returncode=0,
                    stdout=str(attempt["stdout"]),
                    stderr=str(attempt["stderr"]),
                    message="Macro executada via Python embutido do FreeCAD.",
                    mode="python_embedded",
                    output_paths=created,
                    attempts=tuple(attempts),
                )
    binaries = discover_freecad_binaries()
    if not binaries:
        return RunResult(
            ok=False,
            command=tuple(str(part) for part in attempts[-1]["command"]) if attempts else (),
            returncode=attempts[-1]["returncode"] if attempts else None,
            stdout=str(attempts[-1]["stdout"]) if attempts else "",
            stderr=str(attempts[-1]["stderr"]) if attempts else "",
            message="Macro gerada com sucesso, mas FreeCAD nao encontrado para execucao automatica.",
            mode=str(attempts[-1]["mode"]) if attempts else "not_found",
            output_paths={},
            attempts=tuple(attempts),
        )
    for binary in binaries:
        for mode, invocation in _invocations_for(binary, script_path, include_gui=include_gui):
            attempt = _run_invocation(mode, invocation, output_dir, timeout, env)
            attempts.append(attempt)
            created = _created_outputs(expected, output_dir)
            if attempt["returncode"] == 0 and created:
                return RunResult(
                    ok=True,
                    command=tuple(str(part) for part in invocation),
                    returncode=0,
                    stdout=str(attempt["stdout"]),
                    stderr=str(attempt["stderr"]),
                    message="Macro executada e arquivos de saida gerados.",
                    mode=mode,
                    output_paths=created,
                    attempts=tuple(attempts),
                )

    stdout = "\n\n".join(
        f"[{item['mode']}] {' '.join(str(part) for part in item['command'])}\n"
        f"returncode={item['returncode']} timeout={item['timeout']}\n"
        f"stdout:\n{item['stdout']}\n"
        f"stderr:\n{item['stderr']}"
        for item in attempts
    )
    return RunResult(
        ok=False,
        command=tuple(str(part) for part in attempts[-1]["command"]) if attempts else (),
        returncode=attempts[-1]["returncode"] if attempts else None,
        stdout=stdout,
        stderr="",
        message="FreeCAD foi encontrado, mas nenhuma tentativa gerou os arquivos esperados.",
        mode=str(attempts[-1]["mode"]) if attempts else "unknown",
        output_paths=_created_outputs(expected, output_dir),
        attempts=tuple(attempts),
    )


def write_minimal_test_script(path: Path | None = None, output_dir: Path = OUTPUT_DIR) -> Path:
    DIAGNOSTICS_DIR.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    script_path = path or (DIAGNOSTICS_DIR / "freecad_minimal_test.py")
    fcstd = output_dir / "minimal_test.FCStd"
    step = output_dir / "minimal_test.step"
    script_path.write_text(
        "\n".join(
            [
                "import FreeCAD as App",
                "import Part",
                f"doc = App.newDocument('MinimalTest')",
                "box = Part.makeBox(10, 20, 5)",
                "obj = doc.addObject('Part::Feature', 'Box')",
                "obj.Shape = box",
                "doc.recompute()",
                f"doc.saveAs({str(fcstd)!r})",
                f"Part.export([obj], {str(step)!r})",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return script_path


def run_minimal_test(output_dir: Path = OUTPUT_DIR) -> RunResult:
    script = write_minimal_test_script(output_dir=output_dir)
    result = run_macro(script, output_dir=output_dir, timeout=120)
    minimal_outputs = {
        "FCStd": output_dir / "minimal_test.FCStd",
        "STEP": output_dir / "minimal_test.step",
    }
    if all(path.exists() for path in minimal_outputs.values()):
        return RunResult(
            ok=True,
            command=result.command,
            returncode=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
            message="Teste minimo FreeCAD executado com sucesso.",
            mode=result.mode,
            output_paths=minimal_outputs,
            attempts=result.attempts,
        )
    return result


def write_execution_report(
    result: RunResult,
    macro_path: Path,
    report_path: Path | None = None,
    solution: str = "",
) -> Path:
    report_path = report_path or (DIAGNOSTICS_DIR / "freecad_execution_report.md")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    binary = find_freecad_executable()
    outputs = "\n".join(f"- {kind}: {path}" for kind, path in result.output_paths.items()) or "- Nenhum arquivo confirmado."
    attempts = "\n\n".join(
        "\n".join(
            [
                f"### Tentativa {index}: {item.get('mode')}",
                f"Comando: `{' '.join(str(part) for part in item.get('command', []))}`",
                f"Retorno: {item.get('returncode')}",
                f"Timeout: {item.get('timeout')}",
                "Stdout:",
                "```text",
                str(item.get("stdout", ""))[-5000:],
                "```",
                "Stderr:",
                "```text",
                str(item.get("stderr", ""))[-5000:],
                "```",
            ]
        )
        for index, item in enumerate(result.attempts, start=1)
    ) or "Sem tentativas registradas."
    report_path.write_text(
        "\n".join(
            [
                "# FreeCAD Execution Report",
                "",
                f"- Binario FreeCAD encontrado: `{binary or 'nao encontrado'}`",
                f"- Versao: `{get_freecad_version(binary) if binary else 'nao encontrada'}`",
                f"- Modo que funcionou/ultimo modo: `{result.mode}`",
                f"- Comando final: `{' '.join(result.command) if result.command else '(nenhum)'}`",
                f"- Codigo de retorno: `{result.returncode}`",
                f"- Macro: `{macro_path}`",
                "",
                "## Arquivos Gerados",
                outputs,
                "",
                "## Resultado",
                result.message,
                "",
                "## Solucao Aplicada / Proximo Passo",
                solution or ("Executor usou AppImage/console local." if result.ok else "Instale dependencias ausentes ou revise stdout/stderr acima."),
                "",
                "## Tentativas",
                attempts,
                "",
            ]
        ),
        encoding="utf-8",
    )
    return report_path
