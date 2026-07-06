from __future__ import annotations

from app.models import PartSpec
from app.utils import format_mm


def render_flange_body(spec: PartSpec) -> str:
    d = spec.dimensions
    outer_diameter = float(d.get("outer_diameter", d.get("diameter", 100.0)))
    thickness = float(d.get("thickness", 10.0))
    center_hole_feature = spec.feature("center_hole")
    center_hole_diameter = (
        float(center_hole_feature.params.get("diameter", d.get("center_hole_diameter", d.get("center_hole", 0.0))))
        if center_hole_feature
        else 0.0
    )
    hole_count = int(d.get("hole_count", 0) or 0)
    hole_diameter = float(d.get("hole_diameter", 0.0) or 0.0)
    bolt_circle_radius = float(
        d.get(
            "bolt_circle_radius",
            float(d.get("bolt_circle_diameter", d.get("bolt_circle", outer_diameter * 0.68))) / 2.0,
        )
    )

    lines = [
        f"outer_diameter = {format_mm(outer_diameter)}",
        "outer_radius = outer_diameter / 2.0",
        f"thickness = {format_mm(thickness)}",
        f"center_hole_diameter = {format_mm(center_hole_diameter)}",
        "center_hole_radius = center_hole_diameter / 2.0",
        f"hole_diameter = {format_mm(hole_diameter)}",
        "hole_radius = hole_diameter / 2.0",
        f"hole_count = {hole_count}",
        f"bolt_circle_radius = {format_mm(bolt_circle_radius)}",
        "cut_height = thickness + 4.0",
        "cut_z = -2.0",
        "shape = Part.makeCylinder(outer_radius, thickness, Vector(0, 0, 0), Vector(0, 0, 1))",
        "if center_hole_radius > 0:",
        "    center_cut = Part.makeCylinder(center_hole_radius, cut_height, Vector(0, 0, cut_z), Vector(0, 0, 1))",
        "    shape = shape.cut(center_cut)",
        "if hole_count > 0 and hole_radius > 0:",
        "    for idx in range(hole_count):",
        "        angle = 2.0 * math.pi * idx / hole_count",
        "        x = bolt_circle_radius * math.cos(angle)",
        "        y = bolt_circle_radius * math.sin(angle)",
        "        cut = Part.makeCylinder(hole_radius, cut_height, Vector(x, y, cut_z), Vector(0, 0, 1))",
        "        shape = shape.cut(cut)",
        "try:",
        "    shape = shape.removeSplitter()",
        "except Exception as exc:",
        "    log(f'removeSplitter skipped for flange: {exc}')",
    ]
    return "\n".join(lines)
