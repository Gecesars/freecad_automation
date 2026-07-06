from __future__ import annotations

import json
from pathlib import Path

from app.viewer3d.inspection import InspectionResult


def write_inspection_report(result: InspectionResult, output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "inspection_report.json"
    md_path = output_dir / "inspection_report.md"
    payload = result.to_dict()
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = ["# Relatorio de Inspecao CAD", "", f"Status geral: `{result.overall_status}`", ""]
    lines.append("| Item | Esperado | Medido | Erro | Tolerancia | Status |")
    lines.append("| --- | ---: | ---: | ---: | ---: | --- |")
    for check in result.checks:
        lines.append(
            "| {name} | {expected} | {measured} | {error} | {tolerance} | {status} |".format(
                name=check.name,
                expected="-" if check.expected is None else check.expected,
                measured="-" if check.measured is None else check.measured,
                error="-" if check.error is None else f"{check.error:.4f}",
                tolerance="-" if check.tolerance is None else check.tolerance,
                status=check.status,
            )
        )
    notes = [check for check in result.checks if check.note]
    if notes:
        lines.extend(["", "## Notas", ""])
        for check in notes:
            lines.append(f"- {check.name}: {check.note}")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return md_path, json_path
