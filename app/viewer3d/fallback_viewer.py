from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QGraphicsLineItem, QGraphicsScene, QGraphicsView

from app.viewer3d.base import ViewerStatus


class FallbackMeshViewer(QGraphicsView):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.setRenderHint(QPainter.Antialiasing, True)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.vertices = None
        self.faces = None
        self.loaded_path: Path | None = None
        self.rot_x = -35.0
        self.rot_z = 35.0
        self.zoom = 1.0
        self.show_axes = False
        self.show_bbox = False
        self.display_mode = "shaded"
        self.material_color = QColor("#c0cad6")
        self.background_color = QColor("#ffffff")
        self.face_alpha = 245
        self._last_pos = None
        self.setBackgroundBrush(self.background_color)

    def load_mesh(self, path: Path) -> ViewerStatus:
        try:
            import numpy as np
            import trimesh

            mesh = trimesh.load_mesh(str(path), force="mesh")
            if mesh.is_empty:
                return ViewerStatus("mesh_fallback", False, "Malha vazia.", path)
            self.vertices = np.asarray(mesh.vertices, dtype=float)
            self.faces = np.asarray(mesh.faces, dtype=int)
            self.loaded_path = path
            self.zoom_extents()
            self.render_scene()
            return ViewerStatus("mesh_fallback", True, f"Malha carregada: {len(self.vertices)} vertices, {len(self.faces)} faces.", path)
        except Exception as exc:
            return ViewerStatus("mesh_fallback", False, f"Falha ao carregar malha: {exc}", path)

    def set_mesh_data(self, vertices, faces, path: Path | None = None) -> ViewerStatus:
        try:
            import numpy as np

            self.vertices = np.asarray(vertices, dtype=float)
            self.faces = np.asarray(faces, dtype=int)
            self.loaded_path = path
            if self.vertices.size == 0 or self.faces.size == 0:
                return ViewerStatus("mesh_fallback", False, "Malha vazia.", path)
            self.zoom_extents()
            self.render_scene()
            return ViewerStatus("mesh_fallback", True, f"Malha carregada: {len(self.vertices)} vertices, {len(self.faces)} faces.", path)
        except Exception as exc:
            return ViewerStatus("mesh_fallback", False, f"Falha ao aplicar malha no viewer: {exc}", path)

    def set_view(self, view: str) -> None:
        if view == "front":
            self.rot_x, self.rot_z = 0.0, 0.0
        elif view == "top":
            self.rot_x, self.rot_z = -90.0, 0.0
        elif view == "side":
            self.rot_x, self.rot_z = 0.0, 90.0
        else:
            self.rot_x, self.rot_z = -35.0, 35.0
        self.render_scene()

    def zoom_extents(self) -> None:
        self.zoom = 1.0
        self.fitInView(self.scene().itemsBoundingRect(), Qt.KeepAspectRatio)

    def reset_view(self) -> None:
        self.rot_x, self.rot_z, self.zoom = -35.0, 35.0, 1.0
        self.render_scene()

    def set_display_mode(self, mode: str) -> None:
        self.display_mode = mode
        self.render_scene()

    def set_material_color(self, color: QColor) -> None:
        self.material_color = QColor(color)
        self.render_scene()

    def set_background_color(self, color: QColor) -> None:
        self.background_color = QColor(color)
        self.setBackgroundBrush(self.background_color)
        self.render_scene()

    def set_transparency(self, alpha: int) -> None:
        self.face_alpha = max(20, min(255, int(alpha)))
        self.render_scene()

    def wheelEvent(self, event) -> None:
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        self.scale(factor, factor)

    def mousePressEvent(self, event) -> None:
        self._last_pos = event.position()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._last_pos is not None and event.buttons() & Qt.LeftButton:
            delta = event.position() - self._last_pos
            self.rot_z += delta.x() * 0.4
            self.rot_x += delta.y() * 0.4
            self._last_pos = event.position()
            self.render_scene()
        super().mouseMoveEvent(event)

    def render_scene(self) -> None:
        self.scene().clear()
        if self.vertices is None or self.faces is None:
            self.scene().addText("Nenhuma malha carregada")
            return
        import math
        import numpy as np

        verts = self.vertices.copy()
        original_min = verts.min(axis=0)
        original_max = verts.max(axis=0)
        center = (original_min + original_max) / 2
        verts -= center
        rx = math.radians(self.rot_x)
        rz = math.radians(self.rot_z)
        rot_x = np.array([[1, 0, 0], [0, math.cos(rx), -math.sin(rx)], [0, math.sin(rx), math.cos(rx)]])
        rot_z = np.array([[math.cos(rz), -math.sin(rz), 0], [math.sin(rz), math.cos(rz), 0], [0, 0, 1]])
        projected = verts @ rot_x.T @ rot_z.T
        scale = 320 / max(float(np.ptp(projected[:, 0])), float(np.ptp(projected[:, 1])), 1.0)
        pts = projected[:, :2] * scale
        edge_pen = QPen(QColor("#1d2733"), 0.6)
        face_pen = QPen(Qt.NoPen) if self.display_mode == "shaded" else QPen(QColor("#8798aa"), 0.25)
        face_color = QColor(self.material_color)
        face_color.setAlpha(self.face_alpha)
        if self.display_mode in {"shaded", "shaded_with_edges"}:
            for face in self.faces:
                polygon = [QPointF(float(pts[index, 0]), float(-pts[index, 1])) for index in face]
                item = self.scene().addPolygon(polygon, face_pen, face_color)
                item.setZValue(float(projected[face, 2].mean()))
        if self.display_mode in {"wireframe", "shaded_with_edges"}:
            seen: set[tuple[int, int]] = set()
            for face in self.faces:
                for i, a in enumerate(face):
                    b = face[(i + 1) % len(face)]
                    key = tuple(sorted((int(a), int(b))))
                    if key in seen:
                        continue
                    seen.add(key)
                    self.scene().addLine(float(pts[a, 0]), float(-pts[a, 1]), float(pts[b, 0]), float(-pts[b, 1]), edge_pen)
        if self.show_bbox:
            bbox = np.array(
                [
                    [original_min[0], original_min[1], original_min[2]],
                    [original_max[0], original_min[1], original_min[2]],
                    [original_max[0], original_max[1], original_min[2]],
                    [original_min[0], original_max[1], original_min[2]],
                    [original_min[0], original_min[1], original_max[2]],
                    [original_max[0], original_min[1], original_max[2]],
                    [original_max[0], original_max[1], original_max[2]],
                    [original_min[0], original_max[1], original_max[2]],
                ],
                dtype=float,
            )
            bbox = (bbox - center) @ rot_x.T @ rot_z.T
            bbox_pts = bbox[:, :2] * scale
            self._draw_bbox(bbox_pts)
        if self.show_axes:
            self._draw_axes()
        self.fitInView(self.scene().itemsBoundingRect(), Qt.KeepAspectRatio)

    def _draw_axes(self) -> None:
        pens = {"X": QPen(QColor("#c0392b"), 2), "Y": QPen(QColor("#27ae60"), 2), "Z": QPen(QColor("#2980b9"), 2)}
        self.scene().addLine(0, 0, 70, 0, pens["X"])
        self.scene().addText("X").setPos(74, -10)
        self.scene().addLine(0, 0, 0, -70, pens["Y"])
        self.scene().addText("Y").setPos(4, -82)
        self.scene().addLine(0, 0, -48, 48, pens["Z"])
        self.scene().addText("Z").setPos(-66, 42)

    def _draw_bbox(self, bbox_pts) -> None:
        pen = QPen(QColor("#6f7d8c"), 1.0, Qt.DashLine)
        edges = (
            (0, 1),
            (1, 2),
            (2, 3),
            (3, 0),
            (4, 5),
            (5, 6),
            (6, 7),
            (7, 4),
            (0, 4),
            (1, 5),
            (2, 6),
            (3, 7),
        )
        for a, b in edges:
            self.scene().addLine(
                float(bbox_pts[a, 0]),
                float(-bbox_pts[a, 1]),
                float(bbox_pts[b, 0]),
                float(-bbox_pts[b, 1]),
                pen,
            )

    def export_png(self, path: Path) -> Path:
        image = self.grab()
        path.parent.mkdir(parents=True, exist_ok=True)
        image.save(str(path), "PNG")
        return path
