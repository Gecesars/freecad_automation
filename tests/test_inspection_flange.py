from __future__ import annotations

from app.viewer3d.inspection import run_inspection


def test_flange_inspection_uses_bbox_and_metadata() -> None:
    metadata = {
        "part_type": "flange",
        "parameters": {
            "outer_diameter": 100.0,
            "thickness": 12.0,
            "hole_count": 8,
            "hole_diameter": 12.0,
            "bolt_circle_radius": 30.0,
            "bolt_circle_diameter": 60.0,
        },
    }
    mesh_stats = {"bbox": {"x": 100.0, "y": 99.98, "z": 12.0}, "triangles": 4564, "points": 2268}
    result = run_inspection(metadata, mesh_stats, tolerance=0.20)
    checks = {check.name: check for check in result.checks}
    assert checks["Diametro externo"].status == "ok"
    assert checks["Espessura"].status == "ok"
    assert checks["Furos"].status == "ok"
    assert checks["PCD"].status == "ok"
    assert result.overall_status == "warning"
