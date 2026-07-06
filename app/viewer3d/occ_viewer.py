from __future__ import annotations

from app.viewer3d.base import ViewerStatus


def probe_occ_viewer() -> ViewerStatus:
    try:
        import OCC  # type: ignore

        return ViewerStatus("occ_viewer", True, "pythonOCC disponivel.")
    except Exception as exc:
        return ViewerStatus("occ_viewer", False, f"pythonOCC indisponivel: {exc}")
