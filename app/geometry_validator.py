from __future__ import annotations

from dataclasses import replace
from typing import Any

from app.models import Feature, PartSpec
from app.utils import format_mm


def _dimensions(spec: PartSpec | dict[str, Any]) -> dict[str, Any]:
    if isinstance(spec, PartSpec):
        return spec.dimensions
    return dict(spec.get("dimensions", {}))


def _part_type(spec: PartSpec | dict[str, Any]) -> str:
    if isinstance(spec, PartSpec):
        return spec.part_type
    return str(spec.get("part_type", ""))


def validate_geometry(spec: PartSpec | dict[str, Any], edge_margin: float = 1.0) -> dict[str, Any]:
    if _part_type(spec) != "flange":
        return {"valid": True, "error_type": "", "message": "Geometria valida.", "warnings": []}

    d = _dimensions(spec)
    outer_diameter = float(d.get("outer_diameter", d.get("diameter", 0.0)))
    hole_count = int(d.get("hole_count", 0) or 0)
    hole_diameter = float(d.get("hole_diameter", 0.0) or 0.0)
    bolt_circle_radius = d.get("bolt_circle_radius")
    if bolt_circle_radius is None and d.get("bolt_circle") is not None:
        bolt_circle_radius = float(d["bolt_circle"]) / 2.0
    if bolt_circle_radius is None and d.get("bolt_circle_diameter") is not None:
        bolt_circle_radius = float(d["bolt_circle_diameter"]) / 2.0
    bolt_circle_radius = float(bolt_circle_radius or 0.0)

    outer_radius = outer_diameter / 2.0
    hole_radius = hole_diameter / 2.0
    max_allowed = outer_radius - hole_radius - edge_margin
    payload: dict[str, Any] = {
        "valid": True,
        "error_type": "",
        "message": "Geometria valida.",
        "edge_margin": edge_margin,
        "outer_diameter": outer_diameter,
        "outer_radius": outer_radius,
        "hole_count": hole_count,
        "hole_diameter": hole_diameter,
        "hole_radius": hole_radius,
        "bolt_circle_radius": bolt_circle_radius,
        "max_allowed_bolt_radius": max_allowed,
        "warnings": [],
    }

    center_hole = float(d.get("center_hole_diameter", d.get("center_hole", 0.0)) or 0.0)
    if center_hole and center_hole >= outer_diameter:
        payload.update(
            {
                "valid": False,
                "error_type": "center_hole_outside_part",
                "message": (
                    f"Geometria invalida: o furo central de {format_mm(center_hole)} mm "
                    f"e maior ou igual ao diametro externo de {format_mm(outer_diameter)} mm."
                ),
                "suggested_fix": "Reduza o furo central ou aumente o diametro externo da flange.",
            }
        )
        return payload

    if hole_count and hole_diameter and bolt_circle_radius > max_allowed:
        corrected_radius = bolt_circle_radius / 2.0
        corrected_valid = corrected_radius <= max_allowed
        payload.update(
            {
                "valid": False,
                "error_type": "bolt_circle_outside_part",
                "message": (
                    f"Geometria invalida: o raio dos furos informado e {format_mm(bolt_circle_radius)} mm, "
                    f"mas o flange tem raio externo de apenas {format_mm(outer_radius)} mm. "
                    f"Para furos de {format_mm(hole_diameter)} mm, o raio maximo recomendado do "
                    f"circulo de furos e {format_mm(max_allowed)} mm. "
                    f"Voce quis dizer diametro primitivo de {format_mm(bolt_circle_radius)} mm?"
                ),
                "suggested_fix": (
                    f"Interpretar raio de {format_mm(bolt_circle_radius)} mm como diametro primitivo, "
                    f"usando raio {format_mm(corrected_radius)} mm."
                )
                if corrected_valid
                else "Reduza o raio dos furos ou aumente o diametro externo da flange.",
                "can_autocorrect": corrected_valid,
                "corrected_dimensions": {
                    "bolt_circle_diameter": bolt_circle_radius,
                    "bolt_circle_radius": corrected_radius,
                    "bolt_circle": bolt_circle_radius,
                }
                if corrected_valid
                else {},
            }
        )
    return payload


def apply_geometry_autocorrection(
    spec: PartSpec,
    auto_correct: bool = True,
    edge_margin: float = 1.0,
) -> tuple[PartSpec, dict[str, Any]]:
    report = validate_geometry(spec, edge_margin=edge_margin)
    if report.get("valid") or not auto_correct or not report.get("can_autocorrect"):
        return spec, report

    corrected = dict(spec.dimensions)
    corrected.update(report.get("corrected_dimensions", {}))
    features: list[Feature] = []
    for feature in spec.features:
        if feature.kind == "bolt_circle_holes":
            params = dict(feature.params)
            params["radius"] = corrected["bolt_circle_radius"]
            params["diameter_primitive"] = corrected["bolt_circle_diameter"]
            features.append(Feature(feature.kind, params))
        else:
            features.append(feature)

    note = str(report["suggested_fix"])
    new_spec = replace(
        spec,
        dimensions=corrected,
        features=tuple(features),
        assumptions=tuple(dict.fromkeys((*spec.assumptions, note))),
        warnings=tuple(dict.fromkeys((*spec.warnings, report["message"]))),
    )
    corrected_report = validate_geometry(new_spec, edge_margin=edge_margin)
    corrected_report["autocorrected_from"] = report
    corrected_report["autocorrection"] = note
    return new_spec, corrected_report
