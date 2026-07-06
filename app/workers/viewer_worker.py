from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.viewer3d.fallback_image_viewer import generate_mesh_previews
from app.workers.mesh_loader_worker import MeshLoaderWorker


@dataclass(frozen=True)
class ViewerWorkerResult:
    ok: bool
    viewer_mode: str
    mesh_path: Path | None = None
    message: str = ""
    vertices: Any = None
    faces: Any = None
    bbox: dict[str, float] = field(default_factory=dict)
    face_count: int = 0
    vertex_count: int = 0
    preview_images: dict[str, Path] = field(default_factory=dict)
    display_mesh_path: Path | None = None
    original_face_count: int = 0
    original_vertex_count: int = 0
    lod_mode: str = "complete"
    load_seconds: float = 0.0
    error: str = ""


class ViewerWorker:
    def prepare(self, mesh_path: Path, output_dir: Path, max_faces: int = 250_000) -> ViewerWorkerResult:
        try:
            mesh_path = mesh_path.expanduser().resolve()
            info = MeshLoaderWorker().prepare(mesh_path, output_dir)
            if not info.ok or info.display_path is None:
                raise ValueError(info.error or info.message)
            previews = generate_mesh_previews(mesh_path, output_dir)
            return ViewerWorkerResult(
                ok=True,
                viewer_mode="vtk",
                mesh_path=mesh_path,
                message=info.message,
                bbox=info.bbox or {},
                face_count=info.triangles,
                vertex_count=info.points,
                preview_images=previews,
                display_mesh_path=info.display_path,
                original_face_count=info.original_triangles or info.triangles,
                original_vertex_count=info.original_points or info.points,
                lod_mode=info.mode,
                load_seconds=info.load_seconds,
            )
        except Exception as exc:
            previews: dict[str, Path] = {}
            try:
                previews = generate_mesh_previews(mesh_path, output_dir)
            except Exception:
                pass
            return ViewerWorkerResult(
                ok=bool(previews),
                viewer_mode="image" if previews else "unavailable",
                mesh_path=mesh_path,
                message="Viewer 3D falhou; usando preview PNG." if previews else "Falha ao carregar viewer e gerar preview.",
                preview_images=previews,
                error=str(exc),
            )
