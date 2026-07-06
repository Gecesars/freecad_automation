#!/usr/bin/env python3
from __future__ import annotations

import time
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.settings import DIAGNOSTICS_DIR, OUTPUT_DIR
from app.viewer3d.vtk_lod import prepare_mesh_lod, read_polydata


def _approx_memory_mb(points: int, triangles: int) -> float:
    return ((points * 3 * 8) + (triangles * 3 * 4)) / (1024 * 1024)


def _write_sample(path: Path) -> Path:
    import vtkmodules.all as vtk

    path.parent.mkdir(parents=True, exist_ok=True)
    source = vtk.vtkCylinderSource()
    source.SetRadius(50.0)
    source.SetHeight(12.0)
    source.SetResolution(96)
    source.Update()
    triangle = vtk.vtkTriangleFilter()
    triangle.SetInputConnection(source.GetOutputPort())
    triangle.Update()
    writer = vtk.vtkSTLWriter()
    writer.SetFileName(str(path))
    writer.SetInputConnection(triangle.GetOutputPort())
    writer.Write()
    return path


def _render_once(mesh_path: Path) -> float:
    import vtkmodules.all as vtk

    polydata = read_polydata(mesh_path)
    mapper = vtk.vtkPolyDataMapper()
    mapper.SetInputData(polydata)
    mapper.ScalarVisibilityOff()
    actor = vtk.vtkActor()
    actor.SetMapper(mapper)
    actor.GetProperty().SetInterpolationToGouraud()
    actor.GetProperty().SetEdgeVisibility(False)
    renderer = vtk.vtkRenderer()
    renderer.AddActor(actor)
    renderer.SetBackground(1.0, 1.0, 1.0)
    window = vtk.vtkRenderWindow()
    window.SetOffScreenRendering(1)
    window.SetMultiSamples(0)
    window.AddRenderer(renderer)
    window.SetSize(900, 700)
    renderer.ResetCamera()
    started = time.perf_counter()
    window.Render()
    elapsed = time.perf_counter() - started
    window.Finalize()
    return elapsed


def main() -> int:
    DIAGNOSTICS_DIR.mkdir(parents=True, exist_ok=True)
    stls = sorted(OUTPUT_DIR.glob("**/*.stl"), key=lambda path: path.stat().st_mtime, reverse=True)
    if not stls:
        stls = [_write_sample(DIAGNOSTICS_DIR / "viewer_benchmark_sample.stl")]
    selected = stls[:3]
    lines = [
        "# Viewer Benchmark",
        "",
        f"Arquivos testados: {len(selected)}",
        "",
        "| Arquivo | Engine | Modo | Tamanho MB | Memoria aprox. MB | Pontos | Triangulos | Orig. pontos | Orig. triangulos | Load s | Render s | BBox |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for stl in selected:
        info = prepare_mesh_lod(stl, DIAGNOSTICS_DIR)
        render_time = _render_once(info.display_path or stl) if info.ok else 0.0
        bbox = info.bbox or {}
        lines.append(
            "| {name} | {engine} | {mode} | {size:.2f} | {memory:.2f} | {points} | {triangles} | {original_points} | {original_triangles} | {load:.4f} | {render:.4f} | {bbox} |".format(
                name=stl.name,
                engine=info.engine,
                mode=info.mode,
                size=stl.stat().st_size / (1024 * 1024),
                memory=_approx_memory_mb(info.points, info.triangles),
                points=info.points,
                triangles=info.triangles,
                original_points=info.original_points or info.points,
                original_triangles=info.original_triangles or info.triangles,
                load=info.load_seconds,
                render=render_time,
                bbox=f"{bbox.get('x', 0):.3f} x {bbox.get('y', 0):.3f} x {bbox.get('z', 0):.3f}",
            )
        )
    report = DIAGNOSTICS_DIR / "viewer_benchmark.md"
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
