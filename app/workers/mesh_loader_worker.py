from __future__ import annotations

from pathlib import Path

from app.viewer3d.vtk_lod import MeshLoadInfo, prepare_mesh_lod


class MeshLoaderWorker:
    def prepare(self, mesh_path: Path, output_dir: Path) -> MeshLoadInfo:
        return prepare_mesh_lod(mesh_path, output_dir)
