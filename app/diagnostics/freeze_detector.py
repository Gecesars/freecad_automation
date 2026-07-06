from __future__ import annotations

import ast
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from app.settings import APP_DIR, DIAGNOSTICS_DIR


@dataclass(frozen=True)
class FreezeFinding:
    severity: str
    file: str
    line: int
    rule: str
    message: str


ALLOWED_FREECADGUI_IMPORTS = {
    "app/viewer3d/freecad_gui_viewer.py",
    "tools/dump_freecad_api.py",
}


class FreezeVisitor(ast.NodeVisitor):
    def __init__(self, path: Path, rel_path: str) -> None:
        self.path = path
        self.rel_path = rel_path
        self.findings: list[FreezeFinding] = []

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            if alias.name == "FreeCADGui" and self.rel_path not in ALLOWED_FREECADGUI_IMPORTS:
                self._add("high", node.lineno, "freecadgui_import", "FreeCADGui importado fora de modulo isolado.")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module == "FreeCADGui" and self.rel_path not in ALLOWED_FREECADGUI_IMPORTS:
            self._add("high", node.lineno, "freecadgui_import", "FreeCADGui importado fora de modulo isolado.")
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        name = self._call_name(node)
        if name in {"subprocess.run", "subprocess.Popen"}:
            has_timeout = any(keyword.arg == "timeout" for keyword in node.keywords)
            if name == "subprocess.run" and not has_timeout:
                self._add("high", node.lineno, "subprocess_without_timeout", "subprocess.run sem timeout.")
            if name == "subprocess.Popen" and "workers/process_runner.py" not in self.rel_path:
                self._add("medium", node.lineno, "raw_popen", "Popen direto fora de ProcessRunner; confirme que nao bloqueia UI.")
        if name and name.endswith(".load_mesh") and "ui_main.py" in self.rel_path:
            self._add("medium", node.lineno, "viewer_load_in_ui", "Carregamento de malha detectado na UI; prefira ViewerWorker.")
        self.generic_visit(node)

    def _call_name(self, node: ast.Call) -> str:
        if isinstance(node.func, ast.Attribute):
            base = self._name(node.func.value)
            return f"{base}.{node.func.attr}" if base else node.func.attr
        return self._name(node.func)

    def _name(self, node: ast.AST) -> str:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            base = self._name(node.value)
            return f"{base}.{node.attr}" if base else node.attr
        return ""

    def _add(self, severity: str, line: int, rule: str, message: str) -> None:
        self.findings.append(FreezeFinding(severity, self.rel_path, line, rule, message))


def run_freeze_diagnostics(root: Path = APP_DIR) -> dict[str, object]:
    findings: list[FreezeFinding] = []
    for path in sorted(root.glob("app/**/*.py")) + sorted(root.glob("tools/**/*.py")):
        rel = str(path.relative_to(root))
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except Exception as exc:
            findings.append(FreezeFinding("medium", rel, 0, "parse_error", str(exc)))
            continue
        visitor = FreezeVisitor(path, rel)
        visitor.visit(tree)
        findings.extend(visitor.findings)
    payload = {
        "total_findings": len(findings),
        "high": len([item for item in findings if item.severity == "high"]),
        "medium": len([item for item in findings if item.severity == "medium"]),
        "findings": [asdict(item) for item in findings],
    }
    write_report(payload)
    return payload


def write_report(payload: dict[str, object]) -> Path:
    DIAGNOSTICS_DIR.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Freeze Report",
        "",
        f"- Findings: `{payload['total_findings']}`",
        f"- High: `{payload['high']}`",
        f"- Medium: `{payload['medium']}`",
        "",
        "| Severidade | Arquivo | Linha | Regra | Mensagem |",
        "| --- | --- | ---: | --- | --- |",
    ]
    for item in payload["findings"]:  # type: ignore[index]
        lines.append(f"| {item['severity']} | {item['file']} | {item['line']} | {item['rule']} | {item['message']} |")
    report_path = DIAGNOSTICS_DIR / "freeze_report.md"
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    (DIAGNOSTICS_DIR / "freeze_report.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return report_path


def main() -> int:
    payload = run_freeze_diagnostics()
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 1 if payload["high"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
