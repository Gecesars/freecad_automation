from __future__ import annotations

from typing import Any

from app.models import PartSpec


def standardize_part_spec(spec: PartSpec) -> dict[str, Any]:
    """Canonical machine-readable request sent to LLMs and CAD tooling."""
    operations: list[dict[str, Any]] = []
    for feature in spec.features:
        params = dict(feature.params)
        operation = {"kind": feature.kind, "params": params}
        if feature.kind == "slot":
            operation["boolean"] = "subtract"
            operation["primitive"] = "rounded_slot"
        elif feature.kind in {"holes", "bolt_circle_holes", "center_hole"}:
            operation["boolean"] = "subtract"
            operation["primitive"] = "cylinder"
        elif feature.kind == "cad_op":
            operation["boolean"] = "fuse" if str(params.get("op", "")).startswith("add") else "cut"
            operation["primitive"] = str(params.get("op", "custom"))
        operations.append(operation)

    return {
        "schema": "prompt_forge_part_spec_v1",
        "units": "mm",
        "intent": {
            "source_prompt": spec.prompt,
            "part_type": spec.part_type,
            "material": spec.material,
        },
        "coordinate_system": {
            "origin": "lower-left-bottom of the base solid unless explicitly specified",
            "x": "length",
            "y": "width",
            "z": "height/thickness",
        },
        "base_dimensions_mm": dict(spec.dimensions),
        "operations": operations,
        "assumptions": list(spec.assumptions),
        "warnings": list(spec.warnings),
        "requirements": [
            "Preserve the base dimensions exactly.",
            "Apply subtractive operations as through-cuts unless a depth is specified.",
            "Assign the final valid Part.Shape to variable 'shape'.",
            "Do not export or save files in the body code.",
        ],
    }
