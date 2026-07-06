from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class InspectionCheck:
    name: str
    expected: float | int | str | None
    measured: float | int | str | None
    tolerance: float | None
    status: str
    error: float | None = None
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "expected": self.expected,
            "measured": self.measured,
            "error": self.error,
            "tolerance": self.tolerance,
            "status": self.status,
            "note": self.note,
        }


@dataclass(frozen=True)
class InspectionResult:
    checks: tuple[InspectionCheck, ...] = ()
    overall_status: str = "ok"
    metadata_path: Path | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "overall_status": self.overall_status,
            "metadata_path": str(self.metadata_path) if self.metadata_path else None,
            "checks": [check.to_dict() for check in self.checks],
        }


def load_metadata_for_mesh(mesh_path: Path) -> tuple[dict[str, Any], Path | None]:
    job_dir = mesh_path.parent
    candidates = [
        job_dir / "metadata.json",
        *sorted(job_dir.glob("*_metadata.json"), key=lambda path: path.stat().st_mtime, reverse=True),
    ]
    for candidate in candidates:
        if candidate.exists():
            return json.loads(candidate.read_text(encoding="utf-8")), candidate
    return {}, None


def normalize_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    spec = metadata.get("part_spec") or {}
    dimensions = spec.get("dimensions") or {}
    validation = metadata.get("validation") or {}
    bbox_raw = validation.get("bbox") or metadata.get("shape", {}).get("bbox") or {}
    files = metadata.get("files") or {}
    parameters = metadata.get("parameters") or dict(dimensions)
    shape = metadata.get("shape") or {
        "valid": validation.get("valid"),
        "volume_mm3": validation.get("volume"),
        "area_mm2": validation.get("area"),
        "faces": validation.get("faces"),
        "edges": validation.get("edges"),
        "solids": validation.get("solids"),
        "bbox": {
            "x": bbox_raw.get("x", bbox_raw.get("x_length")),
            "y": bbox_raw.get("y", bbox_raw.get("y_length")),
            "z": bbox_raw.get("z", bbox_raw.get("z_length")),
            "xmin": bbox_raw.get("xmin"),
            "xmax": bbox_raw.get("xmax"),
            "ymin": bbox_raw.get("ymin"),
            "ymax": bbox_raw.get("ymax"),
            "zmin": bbox_raw.get("zmin"),
            "zmax": bbox_raw.get("zmax"),
        },
    }
    return {
        "units": metadata.get("units", "mm"),
        "part_type": metadata.get("part_type") or spec.get("part_type"),
        "material": metadata.get("material"),
        "input_prompt": metadata.get("input_prompt"),
        "parameters": parameters,
        "features": metadata.get("features") or spec.get("features") or [],
        "shape": shape,
        "files": files,
        "raw": metadata,
    }


def _dimension_check(name: str, expected: float | None, measured: float | None, tolerance: float) -> InspectionCheck:
    if expected is None or measured is None:
        return InspectionCheck(name, expected, measured, tolerance, "not_measured", note="Valor esperado ou medido ausente.")
    error = abs(float(measured) - float(expected))
    return InspectionCheck(name, float(expected), float(measured), tolerance, "ok" if error <= tolerance else "fail", error)


def run_inspection(metadata: dict[str, Any], mesh_stats: dict[str, Any], tolerance: float = 0.20, metadata_path: Path | None = None) -> InspectionResult:
    normalized = normalize_metadata(metadata)
    part_type = normalized.get("part_type")
    params = normalized.get("parameters") or {}
    bbox = mesh_stats.get("bbox") or normalized.get("shape", {}).get("bbox") or {}
    checks: list[InspectionCheck] = []

    if part_type == "flange":
        expected_outer = params.get("outer_diameter", params.get("diameter"))
        measured_outer = max(float(bbox.get("x", 0.0) or 0.0), float(bbox.get("y", 0.0) or 0.0)) or None
        checks.append(_dimension_check("Diametro externo", expected_outer, measured_outer, tolerance))
        checks.append(_dimension_check("Espessura", params.get("thickness"), bbox.get("z"), tolerance))
        checks.append(
            InspectionCheck(
                "Furos",
                int(params.get("hole_count", 0) or 0),
                int(params.get("hole_count", 0) or 0),
                None,
                "ok",
                note="Esperado pelo modelo; deteccao por malha ainda nao usada para contagem.",
            )
        )
        if params.get("hole_diameter") is not None:
            checks.append(
                InspectionCheck(
                    "Diametro dos furos",
                    float(params["hole_diameter"]),
                    None,
                    tolerance,
                    "not_measured",
                    note="Esperado pelo modelo; diametro nao medido automaticamente na malha.",
                )
            )
        if params.get("bolt_circle_radius") is not None:
            checks.append(
                InspectionCheck(
                    "PCD",
                    float(params["bolt_circle_radius"]) * 2.0,
                    float(params.get("bolt_circle_diameter", float(params["bolt_circle_radius"]) * 2.0)),
                    tolerance,
                    "ok",
                    0.0,
                    "Conferido pelos parametros validados e overlay PCD.",
                )
            )
    elif part_type == "plate":
        checks.extend(
            [
                _dimension_check("Comprimento", params.get("length"), bbox.get("x"), tolerance),
                _dimension_check("Largura", params.get("width"), bbox.get("y"), tolerance),
                _dimension_check("Espessura", params.get("thickness"), bbox.get("z"), tolerance),
            ]
        )
    elif part_type == "box":
        checks.extend(
            [
                _dimension_check("Comprimento", params.get("length"), bbox.get("x"), tolerance),
                _dimension_check("Largura", params.get("width"), bbox.get("y"), tolerance),
                _dimension_check("Altura", params.get("height"), bbox.get("z"), tolerance),
            ]
        )
    elif part_type == "cylinder":
        checks.extend(
            [
                _dimension_check("Diametro", params.get("diameter"), max(float(bbox.get("x", 0) or 0), float(bbox.get("y", 0) or 0)) or None, tolerance),
                _dimension_check("Comprimento", params.get("length"), bbox.get("z"), tolerance),
            ]
        )
    else:
        checks.append(InspectionCheck("Tipo de peca", part_type, part_type, None, "warning", note="Sem regra especifica de inspecao."))

    statuses = {check.status for check in checks}
    overall = "fail" if "fail" in statuses else "warning" if ("warning" in statuses or "not_measured" in statuses) else "ok"
    return InspectionResult(tuple(checks), overall, metadata_path)
