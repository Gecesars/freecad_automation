from __future__ import annotations

import json
import re
import shutil
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from app.freecad_runner import run_macro
from app.models import RunResult
from app.settings import OUTPUT_DIR, REPAIRS_DIR


@dataclass(frozen=True)
class RepairAttempt:
    timestamp: str
    macro_path: str
    repaired_path: str | None
    classification: str
    action: str
    ok: bool
    message: str


ERROR_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("indentation", ("IndentationError", "unexpected indent", "unindent does not match")),
    ("import_error", ("ModuleNotFoundError", "ImportError", "No module named")),
    ("api_missing", ("AttributeError", "has no attribute", "is not a member")),
    ("boolean_cut", ("BRep_API", "TopoDS", "Boolean", "cut failed", "fuse failed")),
    ("shape_invalid", ("is null", "shape is invalid", "Invalid shape", "Shape is not valid")),
    ("export_failed", ("STEP export failed", "STL export failed", "OBJ export failed", "export failed")),
    ("path_invalid", ("No such file or directory", "Permission denied", "File name is not valid")),
    ("freecad_not_found", ("FreeCAD nao encontrado", "FreeCAD not found", "not_found")),
    ("qt_xcb_headless", ("xcb", "could not connect to display", "Qt platform plugin", "DISPLAY")),
    ("appimage_permission", ("Permission denied", "AppImage", "not executable")),
    ("fuse_missing", ("FUSE", "libfuse", "Cannot mount AppImage")),
    ("xvfb_missing", ("xvfb-run", "Xvfb", "headless")),
    ("draft_import_missing", ("No module named 'Draft'", "No module named Draft", "No module named Import")),
    ("unsupported_format", ("unsupported format", "Unknown extension", "Cannot open file")),
)


def classify_error(text: str) -> str:
    haystack = text.lower()
    for label, needles in ERROR_PATTERNS:
        if any(needle.lower() in haystack for needle in needles):
            return label
    return "unknown"


class AutoRepairAgent:
    def __init__(self, history_path: Path = REPAIRS_DIR / "repair_history.jsonl") -> None:
        self.history_path = history_path
        self.history_path.parent.mkdir(parents=True, exist_ok=True)

    def repair_and_run(self, macro_path: Path, output_dir: Path = OUTPUT_DIR, max_attempts: int = 3) -> RunResult:
        current = macro_path
        last_result = run_macro(current, output_dir=output_dir)
        if last_result.ok:
            self._record(current, None, "none", "macro already runs", last_result)
            return last_result
        for attempt_index in range(1, max_attempts + 1):
            classification = classify_error(last_result.stdout + "\n" + last_result.stderr + "\n" + last_result.message)
            repaired, action = self._repair_macro(current, classification, attempt_index)
            self._record(current, repaired, classification, action, last_result)
            if repaired is None:
                break
            current = repaired
            last_result = run_macro(current, output_dir=output_dir)
            if last_result.ok:
                self._record(current, None, classification, "repaired macro executed successfully", last_result)
                return last_result
        return last_result

    def _repair_macro(self, macro_path: Path, classification: str, attempt_index: int) -> tuple[Path | None, str]:
        if not macro_path.exists():
            return None, "macro file does not exist"
        original = macro_path.read_text(encoding="utf-8", errors="replace")
        repaired = original
        action = ""

        if classification == "indentation":
            repaired = original.replace("\t", "    ").replace("\ufeff", "")
            repaired = "\n".join(line.rstrip() for line in repaired.splitlines()) + "\n"
            action = "normalized tabs, BOM and trailing whitespace"
        elif classification in {"qt_xcb_headless", "fuse_missing", "xvfb_missing"}:
            repaired = re.sub(r"^\s*import FreeCADGui as Gui\s*$", "", original, flags=re.MULTILINE)
            repaired = repaired.replace('os.environ.get("PROMPT_FORGE_RENDER_THUMBNAIL") == "1"', "False")
            action = "disabled GUI thumbnail block for headless execution"
        elif classification == "path_invalid":
            repaired = original.replace("\\\\", "/")
            action = "normalized path separators"
        elif classification == "api_missing":
            repaired = original.replace(".makeChamfer(", ".makeFillet(")
            action = "replaced unsupported chamfer API call with fillet fallback where present"
        elif classification in {"boolean_cut", "shape_invalid"}:
            repaired = original.replace("shape = shape.cut(tool)", "shape = shape.cut(tool).removeSplitter()")
            action = "added removeSplitter after boolean cuts"
        elif classification == "export_failed":
            repaired = original.replace("Part.export([obj], step_path)", "Part.export([obj], step_path)")
            action = "export failure is external or geometry-specific; no safe text rewrite available"
        else:
            return None, "no safe automatic rewrite for classification"

        if repaired == original:
            return None, action or "classification recognized, but macro did not require text rewrite"
        repaired_path = macro_path.with_name(f"{macro_path.stem}_repair{attempt_index}{macro_path.suffix}")
        shutil.copy2(macro_path, REPAIRS_DIR / f"{macro_path.stem}_original_attempt{attempt_index}{macro_path.suffix}")
        repaired_path.write_text(repaired, encoding="utf-8")
        compile(repaired, str(repaired_path), "exec")
        return repaired_path, action

    def _record(
        self,
        macro_path: Path,
        repaired_path: Path | None,
        classification: str,
        action: str,
        result: RunResult,
    ) -> None:
        entry = RepairAttempt(
            timestamp=datetime.now().isoformat(timespec="seconds"),
            macro_path=str(macro_path),
            repaired_path=str(repaired_path) if repaired_path else None,
            classification=classification,
            action=action,
            ok=result.ok,
            message=result.message,
        )
        with self.history_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(asdict(entry), ensure_ascii=False) + "\n")
