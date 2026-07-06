from __future__ import annotations

from pathlib import Path

from app.viewer3d.base import ViewerStatus


def probe_freecad_gui(fcstd_path: Path | None = None) -> ViewerStatus:
    try:
        import FreeCAD  # type: ignore
        import FreeCADGui  # type: ignore

        if fcstd_path:
            FreeCAD.openDocument(str(fcstd_path))
        return ViewerStatus("freecad_gui_embedded", True, "FreeCADGui importado com sucesso.", fcstd_path)
    except Exception as exc:
        return ViewerStatus("freecad_gui_embedded", False, f"FreeCADGui indisponivel para embed: {exc}", fcstd_path)
