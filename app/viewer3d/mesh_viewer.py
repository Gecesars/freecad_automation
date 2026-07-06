from app.viewer3d.fallback_image_viewer import FallbackImageViewer
from app.viewer3d.fallback_viewer import FallbackMeshViewer


def create_mesh_viewer(parent=None, preferred: str = "vtk"):
    if preferred == "vtk":
        try:
            from app.viewer3d.vtk_viewer import VTKMeshViewer

            return VTKMeshViewer(parent)
        except Exception:
            pass
    return FallbackMeshViewer(parent)


__all__ = ["FallbackMeshViewer", "FallbackImageViewer", "create_mesh_viewer"]
