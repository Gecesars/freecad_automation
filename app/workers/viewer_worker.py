from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.viewer3d.fallback_image_viewer import generate_mesh_previews


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
    error: str = ""


class ViewerWorker:
    def prepare(self, mesh_path: Path, output_dir: Path, max_faces: int = 250_000) -> ViewerWorkerResult:
        try:
            import numpy as np
            import trimesh

            mesh_path = mesh_path.expanduser().resolve()
            mesh = trimesh.load_mesh(str(mesh_path), force="mesh")
            if mesh.is_empty:
                raise ValueError("malha vazia")
            if len(mesh.faces) > max_faces:
                mesh = mesh.simplify_quadric_decimation(face_count=max_faces)
            vertices = np.asarray(mesh.vertices, dtype=float)
            faces = np.asarray(mesh.faces, dtype=int)
            bounds = np.asarray(mesh.bounds, dtype=float)
            lengths = bounds[1] - bounds[0]
            previews = generate_mesh_previews(mesh_path, output_dir)
            return ViewerWorkerResult(
                ok=True,
                viewer_mode="trimesh",
                mesh_path=mesh_path,
                message=f"Malha pronta: {len(vertices)} vertices, {len(faces)} faces.",
                vertices=vertices,
                faces=faces,
                bbox={
                    "x": float(lengths[0]),
                    "y": float(lengths[1]),
                    "z": float(lengths[2]),
                    "xmin": float(bounds[0][0]),
                    "ymin": float(bounds[0][1]),
                    "zmin": float(bounds[0][2]),
                    "xmax": float(bounds[1][0]),
                    "ymax": float(bounds[1][1]),
                    "zmax": float(bounds[1][2]),
                },
                face_count=int(len(faces)),
                vertex_count=int(len(vertices)),
                preview_images=previews,
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
