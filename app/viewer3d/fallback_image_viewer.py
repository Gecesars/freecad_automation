from __future__ import annotations

import math
from pathlib import Path

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QLabel, QScrollArea, QVBoxLayout, QWidget


VIEW_ANGLES = {
    "iso": (-35.0, 35.0),
    "front": (0.0, 0.0),
    "top": (-90.0, 0.0),
    "side": (0.0, 90.0),
}


def project_vertices(vertices, view: str, size: int = 900):
    import numpy as np

    rx_deg, rz_deg = VIEW_ANGLES.get(view, VIEW_ANGLES["iso"])
    verts = vertices.astype(float).copy()
    center = (verts.min(axis=0) + verts.max(axis=0)) / 2
    verts -= center
    rx = math.radians(rx_deg)
    rz = math.radians(rz_deg)
    rot_x = np.array([[1, 0, 0], [0, math.cos(rx), -math.sin(rx)], [0, math.sin(rx), math.cos(rx)]])
    rot_z = np.array([[math.cos(rz), -math.sin(rz), 0], [math.sin(rz), math.cos(rz), 0], [0, 0, 1]])
    projected = verts @ rot_x.T @ rot_z.T
    span = max(float(np.ptp(projected[:, 0])), float(np.ptp(projected[:, 1])), 1.0)
    scale = size * 0.72 / span
    pts = projected[:, :2] * scale
    pts[:, 0] += size / 2
    pts[:, 1] = size / 2 - pts[:, 1]
    return pts, projected


def generate_mesh_previews(mesh_path: Path, output_dir: Path, size: int = 900) -> dict[str, Path]:
    import numpy as np
    import trimesh

    output_dir.mkdir(parents=True, exist_ok=True)
    mesh = trimesh.load_mesh(str(mesh_path), force="mesh")
    if mesh.is_empty:
        raise ValueError("malha vazia")
    vertices = np.asarray(mesh.vertices, dtype=float)
    faces = np.asarray(mesh.faces, dtype=int)
    paths: dict[str, Path] = {}
    for view in ("iso", "front", "top", "side"):
        pts, projected = project_vertices(vertices, view, size=size)
        depths = projected[:, 2]
        order = sorted(range(len(faces)), key=lambda idx: float(depths[faces[idx]].mean()))
        image = QImage(size, size, QImage.Format_ARGB32)
        image.fill(QColor("#ffffff"))
        painter = QPainter(image)
        painter.setRenderHint(QPainter.Antialiasing, True)
        light = np.array([0.25, -0.35, 0.9], dtype=float)
        light /= np.linalg.norm(light)
        for face_index in order:
            face = faces[face_index]
            polygon = [QPointF(float(pts[idx, 0]), float(pts[idx, 1])) for idx in face]
            p0, p1, p2 = projected[face[0]], projected[face[1]], projected[face[2]]
            normal = np.cross(p1 - p0, p2 - p0)
            norm = np.linalg.norm(normal)
            if norm > 0:
                normal = normal / norm
            intensity = 0.64 + 0.32 * abs(float(normal @ light))
            base = np.array([192, 202, 214], dtype=float)
            rgb = np.clip(base * intensity, 0, 255).astype(int)
            face_color = QColor(int(rgb[0]), int(rgb[1]), int(rgb[2]), 255)
            painter.setPen(QPen(face_color, 1))
            painter.setBrush(face_color)
            painter.drawPolygon(polygon)
        painter.end()
        target = output_dir / f"preview_{view}.png"
        image.save(str(target), "PNG")
        paths[view] = target
    return paths


class FallbackImageViewer(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.label = QLabel("Sem preview")
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setMinimumSize(320, 240)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.label)
        layout = QVBoxLayout(self)
        layout.addWidget(scroll)

    def load_image(self, path: Path) -> None:
        self.label.setPixmap(QPixmap(str(path)))
