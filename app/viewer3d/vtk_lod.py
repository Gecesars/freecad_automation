from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class MeshLoadInfo:
    ok: bool
    original_path: Path
    display_path: Path | None
    engine: str
    message: str
    points: int = 0
    triangles: int = 0
    original_points: int = 0
    original_triangles: int = 0
    bounds: tuple[float, float, float, float, float, float] | None = None
    bbox: dict[str, float] | None = None
    mode: str = "complete"
    load_seconds: float = 0.0
    error: str = ""


def vtk_available() -> bool:
    try:
        import vtkmodules.all  # noqa: F401

        return True
    except Exception:
        return False


def read_polydata(path: Path):
    import vtkmodules.all as vtk

    suffix = path.suffix.lower()
    if suffix == ".stl":
        reader = vtk.vtkSTLReader()
    elif suffix == ".obj":
        reader = vtk.vtkOBJReader()
    else:
        raise ValueError(f"Formato de malha nao suportado pelo VTK viewer: {suffix}")
    reader.SetFileName(str(path))
    reader.Update()
    triangle_filter = vtk.vtkTriangleFilter()
    triangle_filter.SetInputConnection(reader.GetOutputPort())
    triangle_filter.Update()
    return triangle_filter.GetOutput()


def polydata_stats(polydata) -> tuple[int, int, tuple[float, float, float, float, float, float], dict[str, float]]:
    bounds = tuple(float(value) for value in polydata.GetBounds())
    bbox = {
        "xmin": bounds[0],
        "xmax": bounds[1],
        "ymin": bounds[2],
        "ymax": bounds[3],
        "zmin": bounds[4],
        "zmax": bounds[5],
        "x": bounds[1] - bounds[0],
        "y": bounds[3] - bounds[2],
        "z": bounds[5] - bounds[4],
    }
    return int(polydata.GetNumberOfPoints()), int(polydata.GetNumberOfCells()), bounds, bbox


def _cache_name(path: Path, target_faces: int) -> str:
    digest = hashlib.sha1(f"{path.resolve()}:{path.stat().st_mtime_ns}:{target_faces}".encode("utf-8")).hexdigest()[:16]
    return f"{path.stem}_{target_faces}_{digest}.stl"


def decimate_polydata(polydata, target_faces: int):
    import vtkmodules.all as vtk

    current = max(int(polydata.GetNumberOfCells()), 1)
    if current <= target_faces:
        return polydata
    reduction = 1.0 - (float(target_faces) / float(current))
    decimator = vtk.vtkQuadricDecimation()
    decimator.SetInputData(polydata)
    decimator.SetTargetReduction(max(0.0, min(0.95, reduction)))
    decimator.Update()
    cleaned = vtk.vtkCleanPolyData()
    cleaned.SetInputConnection(decimator.GetOutputPort())
    cleaned.Update()
    return cleaned.GetOutput()


def write_stl(polydata, path: Path) -> Path:
    import vtkmodules.all as vtk

    path.parent.mkdir(parents=True, exist_ok=True)
    writer = vtk.vtkSTLWriter()
    writer.SetFileName(str(path))
    writer.SetInputData(polydata)
    writer.Write()
    return path


def prepare_mesh_lod(mesh_path: Path, output_dir: Path, direct_limit: int = 100_000) -> MeshLoadInfo:
    started = time.perf_counter()
    mesh_path = mesh_path.expanduser().resolve()
    cache_dir = output_dir / "cache" / "viewer_lod"
    try:
        polydata = read_polydata(mesh_path)
        original_points, original_triangles, original_bounds, original_bbox = polydata_stats(polydata)
        points, triangles, bounds, bbox = original_points, original_triangles, original_bounds, original_bbox
        display_path = mesh_path
        mode = "complete"
        if triangles > direct_limit:
            target = 100_000 if triangles <= 500_000 else 150_000
            display_path = cache_dir / _cache_name(mesh_path, target)
            mode = "decimated"
            if not display_path.exists():
                preview = decimate_polydata(polydata, target)
                write_stl(preview, display_path)
            preview_polydata = read_polydata(display_path)
            points, triangles, bounds, bbox = polydata_stats(preview_polydata)
        elapsed = time.perf_counter() - started
        return MeshLoadInfo(
            ok=True,
            original_path=mesh_path,
            display_path=display_path,
            engine="vtk",
            message=f"Viewer VTK pronto: {points} pontos, {triangles} triangulos ({mode}).",
            points=points,
            triangles=triangles,
            original_points=original_points,
            original_triangles=original_triangles,
            bounds=bounds,
            bbox=bbox,
            mode=mode,
            load_seconds=elapsed,
        )
    except Exception as exc:
        elapsed = time.perf_counter() - started
        return MeshLoadInfo(
            ok=False,
            original_path=mesh_path,
            display_path=None,
            engine="vtk",
            message=f"Falha ao preparar malha VTK: {exc}",
            load_seconds=elapsed,
            error=str(exc),
        )
