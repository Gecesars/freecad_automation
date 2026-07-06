from __future__ import annotations

import math
import json
from pathlib import Path
from typing import Any

from PySide6.QtCore import Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QVBoxLayout, QWidget

from app.viewer3d.base import ViewerStatus
from app.viewer3d.inspection import normalize_metadata
from app.viewer3d.vtk_lod import polydata_stats, read_polydata
from app.viewer3d.vtk_measurement import Measurement
from app.viewer3d.vtk_overlays import make_circle_polydata, make_points_polydata


def _rgb_tuple(value: QColor | tuple[float, float, float] | tuple[int, int, int]) -> tuple[float, float, float]:
    if isinstance(value, QColor):
        return value.redF(), value.greenF(), value.blueF()
    if max(value) > 1:
        return tuple(float(part) / 255.0 for part in value)  # type: ignore[return-value]
    return tuple(float(part) for part in value)  # type: ignore[return-value]


class VTKMeshViewer(QWidget):
    measurementChanged = Signal(dict)
    selectionChanged = Signal(dict)
    contextMenuRequested = Signal(dict)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        import vtkmodules.all as vtk
        from vtkmodules.qt.QVTKRenderWindowInteractor import QVTKRenderWindowInteractor

        self.vtk = vtk
        self.vtk_widget = QVTKRenderWindowInteractor(self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.vtk_widget)

        self.renderer = vtk.vtkRenderer()
        self.renderer.SetBackground(1.0, 1.0, 1.0)
        self.render_window = self.vtk_widget.GetRenderWindow()
        self.render_window.AddRenderer(self.renderer)
        self.render_window.SetMultiSamples(0)
        self.interactor = self.render_window.GetInteractor()
        self.interactor.SetInteractorStyle(vtk.vtkInteractorStyleTrackballCamera())
        self.interactor.Initialize()

        self.mapper = vtk.vtkPolyDataMapper()
        self.mapper.ScalarVisibilityOff()
        self.actor = vtk.vtkActor()
        self.actor.SetMapper(self.mapper)
        self.actor.GetProperty().SetColor(0.72, 0.77, 0.82)
        self.actor.GetProperty().SetOpacity(1.0)
        self.actor.GetProperty().SetInterpolationToGouraud()
        self.actor.GetProperty().SetEdgeVisibility(False)
        self.renderer.AddActor(self.actor)

        self.loaded_path: Path | None = None
        self.loaded_topology_path: Path | None = None
        self.polydata = None
        self.topology: dict[str, Any] = {}
        self.stats: dict[str, Any] = {}
        self.display_mode = "shaded"
        self.show_axes = False
        self.show_grid = False
        self.show_bbox = False
        self.show_dimensions = False
        self.show_pcd = False
        self.show_hole_centers = False
        self.measurement_enabled = False
        self.selection_mode = "camera"
        self._picked_points: list[tuple[float, float, float]] = []
        self._measurement_actors: list[Any] = []
        self._overlay_actors: list[Any] = []
        self._dimension_actors: list[Any] = []
        self._selection_actors: list[Any] = []
        self._topology_actors: list[Any] = []
        self._topology_face_actors: dict[str, dict[str, Any]] = {}
        self._topology_edge_actors: dict[str, dict[str, Any]] = {}
        self._metadata: dict[str, Any] = {}
        self._axes_widget = None
        self._bbox_actor = None
        self._grid_actor = None
        self._click_observer = self.interactor.AddObserver("LeftButtonPressEvent", self._on_left_button_press)
        self._right_click_observer = self.interactor.AddObserver("RightButtonPressEvent", self._on_right_button_press)

    def load_mesh(self, path: str | Path) -> ViewerStatus:
        path = Path(path).expanduser().resolve()
        try:
            polydata = read_polydata(path)
            self._set_polydata(polydata, path)
            return ViewerStatus("vtk", True, self._stats_message(), path)
        except Exception as exc:
            return ViewerStatus("vtk", False, f"Falha VTK ao carregar malha: {exc}", path)

    def load_topology(self, path: str | Path) -> ViewerStatus:
        path = Path(path).expanduser().resolve()
        try:
            topology = json.loads(path.read_text(encoding="utf-8"))
            self._set_topology(topology, path)
            faces = len(topology.get("faces") or [])
            edges = len(topology.get("edges") or [])
            triangles = self.stats.get("triangles", 0)
            points = self.stats.get("points", 0)
            return ViewerStatus("vtk_topology", True, f"Topologia CAD: {faces} faces, {edges} edges, {points} pontos, {triangles} triangulos.", path)
        except Exception as exc:
            return ViewerStatus("vtk_topology", False, f"Falha ao carregar topologia CAD: {exc}", path)

    def set_mesh_data(self, vertices, faces, path: Path | None = None) -> ViewerStatus:
        if path:
            return self.load_mesh(path)
        try:
            import vtkmodules.all as vtk

            points = vtk.vtkPoints()
            for vertex in vertices:
                points.InsertNextPoint(float(vertex[0]), float(vertex[1]), float(vertex[2]))
            cells = vtk.vtkCellArray()
            for face in faces:
                triangle = vtk.vtkTriangle()
                triangle.GetPointIds().SetId(0, int(face[0]))
                triangle.GetPointIds().SetId(1, int(face[1]))
                triangle.GetPointIds().SetId(2, int(face[2]))
                cells.InsertNextCell(triangle)
            polydata = vtk.vtkPolyData()
            polydata.SetPoints(points)
            polydata.SetPolys(cells)
            self._set_polydata(polydata, path)
            return ViewerStatus("vtk", True, self._stats_message(), path)
        except Exception as exc:
            return ViewerStatus("vtk", False, f"Falha ao aplicar malha no VTK viewer: {exc}", path)

    def _set_polydata(self, polydata, path: Path | None) -> None:
        self._clear_topology_actors()
        self.actor.SetVisibility(True)
        self.polydata = polydata
        self.loaded_path = path
        self.loaded_topology_path = None
        self.topology = {}
        points, triangles, bounds, bbox = polydata_stats(polydata)
        self.stats = {
            "points": points,
            "triangles": triangles,
            "bounds": bounds,
            "bbox": bbox,
            "path": str(path) if path else "",
            "engine": "vtk",
        }
        self.clear_selection(render=False)
        self.mapper.SetInputData(polydata)
        self.mapper.Update()
        self._refresh_bbox_actor()
        self._refresh_grid_actor()
        self._refresh_dimension_actors()
        self._refresh_metadata_overlays()
        self.reset_camera()

    def _set_topology(self, topology: dict[str, Any], path: Path) -> None:
        self._clear_topology_actors()
        self.clear_selection(render=False)
        self.actor.SetVisibility(False)
        self.topology = topology
        self.loaded_topology_path = path
        self.loaded_path = Path((topology.get("source_files") or {}).get("BREP") or path)
        self.polydata = None
        self._metadata = normalize_metadata(topology) if topology else self._metadata

        append = self.vtk.vtkAppendPolyData()
        point_count = 0
        triangle_count = 0
        for face in topology.get("faces") or []:
            polydata = self._face_polydata_from_topology(face)
            if polydata is None:
                continue
            append.AddInputData(polydata)
            point_count += int(polydata.GetNumberOfPoints())
            triangle_count += int(polydata.GetNumberOfCells())
            mapper = self.vtk.vtkPolyDataMapper()
            mapper.SetInputData(polydata)
            mapper.ScalarVisibilityOff()
            actor = self.vtk.vtkActor()
            actor.SetMapper(mapper)
            actor.GetProperty().SetColor(*self.actor.GetProperty().GetColor())
            actor.GetProperty().SetOpacity(self.actor.GetProperty().GetOpacity())
            actor.GetProperty().SetInterpolationToGouraud()
            actor.GetProperty().SetEdgeVisibility(False)
            self.renderer.AddActor(actor)
            self._topology_actors.append(actor)
            self._topology_face_actors[self._actor_key(actor)] = {"face": face, "polydata": polydata, "actor": actor}

        for edge in topology.get("edges") or []:
            polydata = self._edge_polydata_from_topology(edge)
            if polydata is None:
                continue
            mapper = self.vtk.vtkPolyDataMapper()
            mapper.SetInputData(polydata)
            mapper.ScalarVisibilityOff()
            actor = self.vtk.vtkActor()
            actor.SetMapper(mapper)
            actor.GetProperty().SetColor(0.12, 0.15, 0.18)
            actor.GetProperty().SetLineWidth(1.2)
            actor.GetProperty().SetOpacity(0.75)
            self.renderer.AddActor(actor)
            self._topology_actors.append(actor)
            self._topology_edge_actors[self._actor_key(actor)] = {"edge": edge, "polydata": polydata, "actor": actor}

        append.Update()
        combined = append.GetOutput()
        self.polydata = combined if combined.GetNumberOfPoints() else None
        points, triangles, bounds, bbox = polydata_stats(combined) if combined.GetNumberOfPoints() else self._stats_from_topology_shape(topology)
        self.stats = {
            "points": point_count or points,
            "triangles": triangle_count or triangles,
            "bounds": bounds,
            "bbox": bbox,
            "path": str(path),
            "engine": "vtk_topology",
            "topology_faces": len(topology.get("faces") or []),
            "topology_edges": len(topology.get("edges") or []),
        }
        self._refresh_bbox_actor()
        self._refresh_grid_actor()
        self._refresh_dimension_actors()
        self._refresh_metadata_overlays()
        self.reset_camera()

    def _clear_topology_actors(self) -> None:
        for actor in self._topology_actors:
            self.renderer.RemoveActor(actor)
        self._topology_actors = []
        self._topology_face_actors = {}
        self._topology_edge_actors = {}

    def _actor_key(self, actor) -> str:
        try:
            return actor.GetAddressAsString("")
        except Exception:
            return str(id(actor))

    def _actor_by_entry(self, entry: dict[str, Any]):
        return entry.get("actor")

    def _face_polydata_from_topology(self, face: dict[str, Any]):
        mesh = face.get("mesh") or {}
        vertices = mesh.get("vertices") or []
        triangles = mesh.get("triangles") or []
        if not vertices or not triangles:
            return None
        points = self.vtk.vtkPoints()
        for vertex in vertices:
            points.InsertNextPoint(float(vertex[0]), float(vertex[1]), float(vertex[2]))
        cells = self.vtk.vtkCellArray()
        for triangle_ids in triangles:
            if len(triangle_ids) < 3:
                continue
            triangle = self.vtk.vtkTriangle()
            triangle.GetPointIds().SetId(0, int(triangle_ids[0]))
            triangle.GetPointIds().SetId(1, int(triangle_ids[1]))
            triangle.GetPointIds().SetId(2, int(triangle_ids[2]))
            cells.InsertNextCell(triangle)
        polydata = self.vtk.vtkPolyData()
        polydata.SetPoints(points)
        polydata.SetPolys(cells)
        return polydata

    def _edge_polydata_from_topology(self, edge: dict[str, Any]):
        raw_points = edge.get("points") or []
        if isinstance(raw_points, dict):
            raw_points = raw_points.get("points") or []
        if len(raw_points) < 2:
            return None
        points = self.vtk.vtkPoints()
        polyline = self.vtk.vtkPolyLine()
        polyline.GetPointIds().SetNumberOfIds(len(raw_points))
        for index, point in enumerate(raw_points):
            points.InsertNextPoint(float(point[0]), float(point[1]), float(point[2]))
            polyline.GetPointIds().SetId(index, index)
        cells = self.vtk.vtkCellArray()
        cells.InsertNextCell(polyline)
        polydata = self.vtk.vtkPolyData()
        polydata.SetPoints(points)
        polydata.SetLines(cells)
        return polydata

    def _stats_from_topology_shape(self, topology: dict[str, Any]) -> tuple[int, int, tuple[float, float, float, float, float, float], dict[str, float]]:
        bbox = ((topology.get("shape") or {}).get("bbox") or {})
        bounds = (
            float(bbox.get("xmin", 0.0) or 0.0),
            float(bbox.get("xmax", bbox.get("x", 0.0)) or 0.0),
            float(bbox.get("ymin", 0.0) or 0.0),
            float(bbox.get("ymax", bbox.get("y", 0.0)) or 0.0),
            float(bbox.get("zmin", 0.0) or 0.0),
            float(bbox.get("zmax", bbox.get("z", 0.0)) or 0.0),
        )
        normalized_bbox = {
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
        return 0, 0, bounds, normalized_bbox

    def _stats_message(self) -> str:
        return f"VTK: {self.stats.get('points', 0)} pontos, {self.stats.get('triangles', 0)} triangulos."

    def clear(self) -> None:
        self.mapper.SetInputData(None)
        self.loaded_path = None
        self.polydata = None
        self.loaded_topology_path = None
        self.topology = {}
        self.stats = {}
        self.clear_measurements()
        self.clear_selection(render=False)
        self._clear_topology_actors()
        self._clear_overlays()
        self._clear_dimension_actors()
        self.render_window.Render()

    def reset_camera(self) -> None:
        self.renderer.ResetCamera()
        self.render_window.Render()

    def zoom_extents(self) -> None:
        self.reset_camera()

    def set_view(self, view: str) -> None:
        if view in {"isometric", "iso"}:
            self.set_view_iso()
        elif view == "front":
            self.set_view_front()
        elif view == "top":
            self.set_view_top()
        elif view in {"side", "right", "direita"}:
            self.set_view_right()
        else:
            self.set_view_iso()

    def set_view_iso(self) -> None:
        self._set_camera_direction((1, -1, 0.75), (0, 0, 1))

    def set_view_front(self) -> None:
        self._set_camera_direction((0, -1, 0), (0, 0, 1))

    def set_view_top(self) -> None:
        self._set_camera_direction((0, 0, 1), (0, 1, 0))

    def set_view_right(self) -> None:
        self._set_camera_direction((1, 0, 0), (0, 0, 1))

    def _set_camera_direction(self, direction: tuple[float, float, float], view_up: tuple[float, float, float]) -> None:
        bounds = self.stats.get("bounds")
        if not bounds:
            self.reset_camera()
            return
        cx = (bounds[0] + bounds[1]) / 2.0
        cy = (bounds[2] + bounds[3]) / 2.0
        cz = (bounds[4] + bounds[5]) / 2.0
        span = max(bounds[1] - bounds[0], bounds[3] - bounds[2], bounds[5] - bounds[4], 1.0)
        norm = math.sqrt(sum(part * part for part in direction)) or 1.0
        unit = tuple(part / norm for part in direction)
        distance = span * 2.4
        camera = self.renderer.GetActiveCamera()
        camera.SetFocalPoint(cx, cy, cz)
        camera.SetPosition(cx + unit[0] * distance, cy + unit[1] * distance, cz + unit[2] * distance)
        camera.SetViewUp(*view_up)
        self.renderer.ResetCameraClippingRange()
        self.render_window.Render()

    def reset_view(self) -> None:
        self.set_view_iso()

    def set_display_mode(self, mode: str) -> None:
        self.display_mode = mode
        prop = self.actor.GetProperty()
        if mode == "wireframe":
            prop.SetRepresentationToWireframe()
            prop.SetEdgeVisibility(True)
        else:
            prop.SetRepresentationToSurface()
            prop.SetEdgeVisibility(mode == "shaded_with_edges")
        for entry in self._topology_face_actors.values():
            actor = self._actor_by_entry(entry)
            if actor is None:
                continue
            face_prop = actor.GetProperty()
            if mode == "wireframe":
                face_prop.SetRepresentationToWireframe()
                face_prop.SetEdgeVisibility(True)
            else:
                face_prop.SetRepresentationToSurface()
                face_prop.SetEdgeVisibility(mode == "shaded_with_edges")
        self.render_window.Render()

    def set_show_edges(self, enabled: bool) -> None:
        self.actor.GetProperty().SetEdgeVisibility(bool(enabled))
        for entry in self._topology_face_actors.values():
            actor = self._actor_by_entry(entry)
            if actor is not None:
                actor.GetProperty().SetEdgeVisibility(bool(enabled))
        self.render_window.Render()

    def set_show_axes(self, enabled: bool) -> None:
        self.show_axes = bool(enabled)
        if self._axes_widget is None:
            axes = self.vtk.vtkAxesActor()
            widget = self.vtk.vtkOrientationMarkerWidget()
            widget.SetOrientationMarker(axes)
            widget.SetInteractor(self.interactor)
            widget.SetViewport(0.0, 0.0, 0.18, 0.18)
            widget.SetEnabled(False)
            widget.InteractiveOff()
            self._axes_widget = widget
        self._axes_widget.SetEnabled(1 if self.show_axes else 0)
        self.render_window.Render()

    def set_show_grid(self, enabled: bool) -> None:
        self.show_grid = bool(enabled)
        self._refresh_grid_actor()
        self.render_window.Render()

    def set_show_bounding_box(self, enabled: bool) -> None:
        self.show_bbox = bool(enabled)
        self._refresh_bbox_actor()
        self.render_window.Render()

    def set_show_dimensions(self, enabled: bool) -> None:
        self.show_dimensions = bool(enabled)
        self._refresh_bbox_actor()
        self._refresh_dimension_actors()
        self.render_window.Render()

    def set_show_pcd(self, enabled: bool) -> None:
        self.show_pcd = bool(enabled)
        self._refresh_metadata_overlays()
        self.render_window.Render()

    def set_show_hole_centers(self, enabled: bool) -> None:
        self.show_hole_centers = bool(enabled)
        self._refresh_metadata_overlays()
        self.render_window.Render()

    def set_opacity(self, value: float) -> None:
        opacity = max(0.05, min(1.0, float(value)))
        self.actor.GetProperty().SetOpacity(opacity)
        for entry in self._topology_face_actors.values():
            actor = self._actor_by_entry(entry)
            if actor is not None:
                actor.GetProperty().SetOpacity(opacity)
        self.render_window.Render()

    def set_transparency(self, alpha: int) -> None:
        self.set_opacity(float(alpha) / 255.0)

    def set_part_color(self, rgb) -> None:
        color = _rgb_tuple(rgb)
        self.actor.GetProperty().SetColor(*color)
        for entry in self._topology_face_actors.values():
            actor = self._actor_by_entry(entry)
            if actor is not None:
                actor.GetProperty().SetColor(*color)
        self.render_window.Render()

    def set_material_color(self, color: QColor) -> None:
        self.set_part_color(color)

    def set_background_color(self, rgb) -> None:
        self.renderer.SetBackground(*_rgb_tuple(rgb))
        self.render_window.Render()

    def set_inspection_metadata(self, metadata: dict[str, Any]) -> None:
        self._metadata = normalize_metadata(metadata) if metadata else {}
        self._refresh_metadata_overlays()
        self.render_window.Render()

    def set_selection_mode(self, mode: str) -> None:
        self.selection_mode = mode if mode in {"camera", "object", "face", "edge", "point"} else "camera"
        self._picked_points = []

    def clear_selection(self, render: bool = True) -> None:
        for actor in self._selection_actors:
            self.renderer.RemoveActor(actor)
        self._selection_actors = []
        if render:
            self.render_window.Render()

    def _refresh_bbox_actor(self) -> None:
        if self._bbox_actor is not None:
            self.renderer.RemoveActor(self._bbox_actor)
            self._bbox_actor = None
        if not (self.show_bbox or self.show_dimensions) or self.polydata is None:
            return
        outline = self.vtk.vtkOutlineFilter()
        outline.SetInputData(self.polydata)
        mapper = self.vtk.vtkPolyDataMapper()
        mapper.SetInputConnection(outline.GetOutputPort())
        actor = self.vtk.vtkActor()
        actor.SetMapper(mapper)
        actor.GetProperty().SetColor(0.15, 0.32, 0.55)
        actor.GetProperty().SetLineWidth(2.0)
        self.renderer.AddActor(actor)
        self._bbox_actor = actor

    def _clear_dimension_actors(self) -> None:
        for actor in self._dimension_actors:
            self.renderer.RemoveActor(actor)
        self._dimension_actors = []

    def _refresh_dimension_actors(self) -> None:
        self._clear_dimension_actors()
        if not self.show_dimensions or not self.stats.get("bounds"):
            return
        bounds = self.stats["bounds"]
        xmin, xmax, ymin, ymax, zmin, zmax = bounds
        x_len = xmax - xmin
        y_len = ymax - ymin
        z_len = zmax - zmin
        span = max(x_len, y_len, z_len, 1.0)
        offset = span * 0.08
        z_top = zmax + offset
        specs = [
            ((xmin, ymin - offset, z_top), (xmax, ymin - offset, z_top), f"X {x_len:.2f} mm", (0.75, 0.10, 0.08)),
            ((xmin - offset, ymin, z_top), (xmin - offset, ymax, z_top), f"Y {y_len:.2f} mm", (0.08, 0.52, 0.16)),
            ((xmax + offset, ymax + offset, zmin), (xmax + offset, ymax + offset, zmax), f"Z {z_len:.2f} mm", (0.08, 0.26, 0.78)),
        ]
        for p1, p2, label, color in specs:
            self._add_dimension_line(p1, p2, color)
            midpoint = tuple((p1[index] + p2[index]) / 2.0 for index in range(3))
            self._add_dimension_label(label, midpoint, color, span)

    def _add_dimension_line(self, p1: tuple[float, float, float], p2: tuple[float, float, float], color: tuple[float, float, float]) -> None:
        line = self.vtk.vtkLineSource()
        line.SetPoint1(*p1)
        line.SetPoint2(*p2)
        mapper = self.vtk.vtkPolyDataMapper()
        mapper.SetInputConnection(line.GetOutputPort())
        actor = self.vtk.vtkActor()
        actor.SetMapper(mapper)
        actor.GetProperty().SetColor(*color)
        actor.GetProperty().SetLineWidth(2.2)
        self.renderer.AddActor(actor)
        self._dimension_actors.append(actor)

    def _add_dimension_label(self, text: str, position: tuple[float, float, float], color: tuple[float, float, float], span: float) -> None:
        vector_text = self.vtk.vtkVectorText()
        vector_text.SetText(text)
        mapper = self.vtk.vtkPolyDataMapper()
        mapper.SetInputConnection(vector_text.GetOutputPort())
        actor = self.vtk.vtkFollower()
        actor.SetMapper(mapper)
        actor.SetCamera(self.renderer.GetActiveCamera())
        actor.SetScale(span * 0.025, span * 0.025, span * 0.025)
        actor.SetPosition(*position)
        actor.GetProperty().SetColor(*color)
        self.renderer.AddActor(actor)
        self._dimension_actors.append(actor)

    def _refresh_grid_actor(self) -> None:
        if self._grid_actor is not None:
            self.renderer.RemoveActor(self._grid_actor)
            self._grid_actor = None
        if not self.show_grid or not self.stats.get("bounds"):
            return
        bounds = self.stats["bounds"]
        span = max(bounds[1] - bounds[0], bounds[3] - bounds[2], 10.0)
        step = max(1.0, round(span / 10.0, 1))
        z = bounds[4]
        points = self.vtk.vtkPoints()
        lines = self.vtk.vtkCellArray()
        xmin, xmax = bounds[0] - step, bounds[1] + step
        ymin, ymax = bounds[2] - step, bounds[3] + step
        idx = 0
        value = xmin
        while value <= xmax + 1e-6:
            points.InsertNextPoint(value, ymin, z)
            points.InsertNextPoint(value, ymax, z)
            line = self.vtk.vtkLine()
            line.GetPointIds().SetId(0, idx)
            line.GetPointIds().SetId(1, idx + 1)
            lines.InsertNextCell(line)
            idx += 2
            value += step
        value = ymin
        while value <= ymax + 1e-6:
            points.InsertNextPoint(xmin, value, z)
            points.InsertNextPoint(xmax, value, z)
            line = self.vtk.vtkLine()
            line.GetPointIds().SetId(0, idx)
            line.GetPointIds().SetId(1, idx + 1)
            lines.InsertNextCell(line)
            idx += 2
            value += step
        polydata = self.vtk.vtkPolyData()
        polydata.SetPoints(points)
        polydata.SetLines(lines)
        mapper = self.vtk.vtkPolyDataMapper()
        mapper.SetInputData(polydata)
        actor = self.vtk.vtkActor()
        actor.SetMapper(mapper)
        actor.GetProperty().SetColor(0.82, 0.86, 0.90)
        actor.GetProperty().SetLineWidth(1.0)
        self.renderer.AddActor(actor)
        self._grid_actor = actor

    def _clear_overlays(self) -> None:
        for actor in self._overlay_actors:
            self.renderer.RemoveActor(actor)
        self._overlay_actors = []

    def _refresh_metadata_overlays(self) -> None:
        self._clear_overlays()
        if not self._metadata or not self.stats.get("bounds"):
            return
        params = self._metadata.get("parameters") or {}
        z = (self.stats["bounds"][5] if self.stats.get("bounds") else 0.0) + 0.4
        if self.show_pcd and self._metadata.get("part_type") == "flange" and params.get("bolt_circle_radius"):
            circle = make_circle_polydata(float(params["bolt_circle_radius"]), z=z)
            self._add_polyline_overlay(circle, (0.05, 0.36, 0.78), 2.5)
        if self.show_hole_centers and self._metadata.get("part_type") == "flange":
            count = int(params.get("hole_count", 0) or 0)
            radius = float(params.get("bolt_circle_radius", 0.0) or 0.0)
            if count > 0 and radius > 0:
                points = [
                    (radius * math.cos(2.0 * math.pi * idx / count), radius * math.sin(2.0 * math.pi * idx / count), z)
                    for idx in range(count)
                ]
                self._add_points_overlay(make_points_polydata(points), (0.86, 0.21, 0.12), 9.0)

    def _add_polyline_overlay(self, polydata, color: tuple[float, float, float], width: float) -> None:
        mapper = self.vtk.vtkPolyDataMapper()
        mapper.SetInputData(polydata)
        actor = self.vtk.vtkActor()
        actor.SetMapper(mapper)
        actor.GetProperty().SetColor(*color)
        actor.GetProperty().SetLineWidth(width)
        self.renderer.AddActor(actor)
        self._overlay_actors.append(actor)

    def _add_points_overlay(self, polydata, color: tuple[float, float, float], size: float) -> None:
        mapper = self.vtk.vtkPolyDataMapper()
        mapper.SetInputData(polydata)
        actor = self.vtk.vtkActor()
        actor.SetMapper(mapper)
        actor.GetProperty().SetColor(*color)
        actor.GetProperty().SetPointSize(size)
        self.renderer.AddActor(actor)
        self._overlay_actors.append(actor)

    def set_measurement_enabled(self, enabled: bool) -> None:
        self.measurement_enabled = bool(enabled)

    def clear_measurements(self) -> None:
        for actor in self._measurement_actors:
            self.renderer.RemoveActor(actor)
        self._measurement_actors = []
        self._picked_points = []
        self.render_window.Render()

    def _pick_main_actor(self) -> tuple[int, tuple[float, float, float]] | None:
        x, y = self.interactor.GetEventPosition()
        picker = self.vtk.vtkCellPicker()
        picker.SetTolerance(0.0015)
        picker.PickFromListOn()
        picker.AddPickList(self.actor)
        if not picker.Pick(float(x), float(y), 0.0, self.renderer):
            return None
        cell_id = int(picker.GetCellId())
        if cell_id < 0:
            return None
        point = tuple(float(value) for value in picker.GetPickPosition())
        return cell_id, point

    def _on_left_button_press(self, obj, event) -> None:
        if not self.measurement_enabled and self.selection_mode == "camera":
            self.interactor.GetInteractorStyle().OnLeftButtonDown()
            return
        mode = "point" if self.selection_mode == "camera" else self.selection_mode
        if self.topology and mode in {"object", "face", "edge", "point"}:
            if self._handle_topology_pick(mode):
                self.render_window.Render()
                return
            if mode != "camera":
                return
        picked = self._pick_main_actor()
        if picked is None:
            if self.selection_mode == "camera":
                self.interactor.GetInteractorStyle().OnLeftButtonDown()
            return
        cell_id, point = picked
        if mode == "object":
            self._select_object()
        elif mode == "face":
            self._select_face(cell_id)
        elif mode == "edge":
            self._select_edge(cell_id, point)
        elif mode == "point":
            self._select_point(cell_id, point)
        self.render_window.Render()

    def _on_right_button_press(self, obj, event) -> None:
        x, y = self.interactor.GetEventPosition()
        payload = {
            "x": int(x),
            "y": int(y),
            "selection_mode": self.selection_mode,
            "measurement_enabled": self.measurement_enabled,
            "engine": self.stats.get("engine", ""),
            "has_topology": bool(self.topology),
            "has_mesh": self.polydata is not None,
            "path": self.stats.get("path", ""),
        }
        self.contextMenuRequested.emit(payload)

    def _handle_topology_pick(self, mode: str) -> bool:
        if mode == "object":
            picked = self._pick_topology_actor("face")
            if not picked:
                return False
            self._select_topology_object()
            return True
        if mode == "face":
            picked = self._pick_topology_actor("face")
            if not picked:
                return False
            entry, _point = picked
            self._select_topology_face(entry)
            return True
        if mode == "edge":
            picked = self._pick_topology_actor("edge")
            if not picked:
                return False
            entry, _point = picked
            self._select_topology_edge(entry)
            return True
        if mode == "point":
            picked = self._pick_topology_actor("face")
            if not picked:
                return False
            _entry, point = picked
            self._select_topology_point(point)
            return True
        return False

    def _pick_topology_actor(self, kind: str) -> tuple[dict[str, Any], tuple[float, float, float]] | None:
        actors = self._topology_edge_actors if kind == "edge" else self._topology_face_actors
        if not actors:
            return None
        x, y = self.interactor.GetEventPosition()
        picker = self.vtk.vtkCellPicker()
        picker.SetTolerance(0.006 if kind == "edge" else 0.0015)
        picker.PickFromListOn()
        for entry in actors.values():
            actor = entry.get("actor")
            if actor is not None:
                picker.AddPickList(actor)
        if not picker.Pick(float(x), float(y), 0.0, self.renderer):
            return None
        actor = picker.GetActor()
        if actor is None:
            return None
        entry = actors.get(self._actor_key(actor))
        if not entry:
            return None
        point = tuple(float(value) for value in picker.GetPickPosition())
        return entry, point

    def _select_topology_object(self) -> None:
        self.clear_selection(render=False)
        if self.polydata is not None:
            outline = self.vtk.vtkOutlineFilter()
            outline.SetInputData(self.polydata)
            mapper = self.vtk.vtkPolyDataMapper()
            mapper.SetInputConnection(outline.GetOutputPort())
            actor = self.vtk.vtkActor()
            actor.SetMapper(mapper)
            actor.GetProperty().SetColor(0.95, 0.48, 0.05)
            actor.GetProperty().SetLineWidth(3.5)
            self.renderer.AddActor(actor)
            self._selection_actors.append(actor)
        self._add_selection_label("Objeto CAD", self._bounds_label_position(), (1.0, 0.72, 0.08))
        payload = {
            "type": "selection_object",
            "source": "cad_topology",
            "part_type": self.topology.get("part_type"),
            "path": self.stats.get("path"),
            "bbox": self.stats.get("bbox") or {},
            "points": self.stats.get("points", 0),
            "triangles": self.stats.get("triangles", 0),
            "cad_faces": len(self.topology.get("faces") or []),
            "cad_edges": len(self.topology.get("edges") or []),
        }
        self.selectionChanged.emit(payload)
        if self.measurement_enabled:
            self.measurementChanged.emit({"type": "object_measurement", **payload})

    def _select_topology_face(self, entry: dict[str, Any]) -> None:
        face = entry["face"]
        polydata = entry["polydata"]
        self.clear_selection(render=False)
        mapper = self.vtk.vtkPolyDataMapper()
        mapper.SetInputData(polydata)
        actor = self.vtk.vtkActor()
        actor.SetMapper(mapper)
        actor.GetProperty().SetColor(1.0, 0.58, 0.05)
        actor.GetProperty().SetOpacity(0.68)
        actor.GetProperty().SetEdgeVisibility(True)
        actor.GetProperty().SetEdgeColor(1.0, 0.90, 0.20)
        actor.GetProperty().SetLineWidth(3.0)
        self.renderer.AddActor(actor)
        self._selection_actors.append(actor)
        center = self._xyz_tuple(face.get("center")) or self._polydata_center(polydata)
        area = float(face.get("area", 0.0) or 0.0)
        self._add_selection_label(f"Face CAD {face.get('id')} | area {area:.2f} mm2", center, (1.0, 0.74, 0.08))
        payload = {
            "type": "selection_face",
            "source": "cad_topology",
            "face_id": face.get("id"),
            "cell_id": face.get("id"),
            "area": float(face.get("area", 0.0) or 0.0),
            "perimeter": None,
            "centroid": self._xyz_tuple(face.get("center")),
            "normal": self._xyz_tuple(face.get("normal")),
            "surface": face.get("surface") or {},
            "bbox": face.get("bbox") or {},
        }
        self.selectionChanged.emit(payload)
        if self.measurement_enabled:
            self.measurementChanged.emit({"type": "face_measurement", **payload})

    def _select_topology_edge(self, entry: dict[str, Any]) -> None:
        edge = entry["edge"]
        polydata = entry["polydata"]
        self.clear_selection(render=False)
        self._add_tube_selection(polydata, (1.0, 0.78, 0.05), opacity=0.85, radius_scale=0.0045)
        self._add_polyline_selection(polydata, (1.0, 0.05, 0.02), 5.5)
        raw_points = edge.get("points") or []
        if isinstance(raw_points, dict):
            raw_points = raw_points.get("points") or []
        if raw_points:
            self._add_sphere_marker(tuple(float(value) for value in raw_points[0]), (1.0, 0.05, 0.02), self._selection_actors, scale=0.009)
            self._add_sphere_marker(tuple(float(value) for value in raw_points[-1]), (1.0, 0.05, 0.02), self._selection_actors, scale=0.009)
        curve = edge.get("curve") or {}
        circular = None
        if edge.get("is_circular") and curve.get("radius") is not None:
            radius = float(curve.get("radius", 0.0) or 0.0)
            center = self._xyz_tuple(curve.get("center")) or (0.0, 0.0, 0.0)
            circular = {
                "name": f"Edge CAD {edge.get('id')}",
                "kind": "cad_curve",
                "center": center,
                "radius": radius,
                "diameter": radius * 2.0,
                "circumference": 2.0 * math.pi * radius,
                "source": "cad_topology",
                "curve_type": curve.get("type"),
                "index": edge.get("id"),
            }
            circle = make_circle_polydata(radius, z=center[2], center=(center[0], center[1]))
            self._add_tube_selection(circle, (0.0, 0.42, 1.0), opacity=0.70, radius_scale=0.003)
            self._add_polyline_selection(circle, (0.0, 0.20, 0.95), 4.5)
            self._add_sphere_marker(center, (0.0, 0.20, 0.95), self._selection_actors, scale=0.010)
        length = float(edge.get("length", 0.0) or 0.0)
        label_position = self._edge_label_position(edge) or self._polydata_center(polydata)
        if circular:
            label = f"Edge CAD {edge.get('id')} | dia {float(circular['diameter']):.2f} mm"
        else:
            label = f"Edge CAD {edge.get('id')} | L {length:.2f} mm"
        self._add_selection_label(label, label_position, (1.0, 0.12, 0.04))
        payload = {
            "type": "selection_edge",
            "source": "cad_topology",
            "edge_id": edge.get("id"),
            "mesh_segment_length": length,
            "cad_length": length,
            "curve": curve,
            "circular": circular,
        }
        self.selectionChanged.emit(payload)
        if self.measurement_enabled:
            self.measurementChanged.emit({"type": "edge_measurement", **payload})

    def _select_topology_point(self, point: tuple[float, float, float]) -> None:
        self.clear_selection(render=False)
        self._add_sphere_marker(point, (0.95, 0.16, 0.08), self._selection_actors, scale=0.011)
        self._add_selection_label("Ponto CAD", point, (0.95, 0.16, 0.08))
        payload = {"type": "selection_point", "source": "cad_topology", "point": point, "cell_id": -1, "normal": None}
        self.selectionChanged.emit(payload)
        if not self.measurement_enabled:
            return
        self._picked_points.append(point)
        self._add_sphere_marker(point, (0.90, 0.18, 0.12), self._measurement_actors, scale=0.008)
        if len(self._picked_points) == 1:
            self.measurementChanged.emit({"type": "point", "point": point, "cell_id": -1, "normal": None})
        elif len(self._picked_points) == 2:
            measurement = Measurement(self._picked_points[0], self._picked_points[1])
            self._add_measurement_line(measurement)
            payload = measurement.to_dict()
            payload["type"] = "distance"
            self.measurementChanged.emit(payload)
            self._picked_points = []

    def _xyz_tuple(self, value: Any) -> tuple[float, float, float] | None:
        if not value:
            return None
        if isinstance(value, dict):
            return (
                float(value.get("x", 0.0) or 0.0),
                float(value.get("y", 0.0) or 0.0),
                float(value.get("z", 0.0) or 0.0),
            )
        if isinstance(value, (list, tuple)) and len(value) >= 3:
            return float(value[0]), float(value[1]), float(value[2])
        return None

    def _select_object(self) -> None:
        self.clear_selection(render=False)
        if self.polydata is None:
            return
        outline = self.vtk.vtkOutlineFilter()
        outline.SetInputData(self.polydata)
        mapper = self.vtk.vtkPolyDataMapper()
        mapper.SetInputConnection(outline.GetOutputPort())
        actor = self.vtk.vtkActor()
        actor.SetMapper(mapper)
        actor.GetProperty().SetColor(0.95, 0.48, 0.05)
        actor.GetProperty().SetLineWidth(3.5)
        self.renderer.AddActor(actor)
        self._selection_actors.append(actor)
        self._add_selection_label("Objeto", self._bounds_label_position(), (1.0, 0.72, 0.08))
        bbox = self.stats.get("bbox") or {}
        payload = {
            "type": "selection_object",
            "part_type": self._metadata.get("part_type"),
            "path": self.stats.get("path"),
            "bbox": bbox,
            "points": self.stats.get("points", 0),
            "triangles": self.stats.get("triangles", 0),
        }
        self.selectionChanged.emit(payload)
        if self.measurement_enabled:
            self.measurementChanged.emit({"type": "object_measurement", **payload})

    def _select_face(self, cell_id: int) -> None:
        points = self._cell_points(cell_id)
        if len(points) < 3:
            return
        self.clear_selection(render=False)
        face_polydata = self._polydata_from_polygon(points)
        mapper = self.vtk.vtkPolyDataMapper()
        mapper.SetInputData(face_polydata)
        actor = self.vtk.vtkActor()
        actor.SetMapper(mapper)
        actor.GetProperty().SetColor(1.0, 0.58, 0.05)
        actor.GetProperty().SetOpacity(0.68)
        actor.GetProperty().SetEdgeVisibility(True)
        actor.GetProperty().SetEdgeColor(1.0, 0.90, 0.20)
        actor.GetProperty().SetLineWidth(3.0)
        self.renderer.AddActor(actor)
        self._selection_actors.append(actor)
        area = self._polygon_area(points)
        perimeter = self._polygon_perimeter(points)
        centroid = self._centroid(points)
        self._add_selection_label(f"Face {cell_id} | area {area:.2f} mm2", centroid, (1.0, 0.74, 0.08))
        normal = self._cell_normal(cell_id)
        payload = {
            "type": "selection_face",
            "cell_id": cell_id,
            "vertices": len(points),
            "area": area,
            "perimeter": perimeter,
            "centroid": centroid,
            "normal": normal,
            "bbox": self._points_bbox(points),
        }
        self.selectionChanged.emit(payload)
        if self.measurement_enabled:
            self.measurementChanged.emit({"type": "face_measurement", **payload})

    def _select_edge(self, cell_id: int, pick_point: tuple[float, float, float]) -> None:
        edge = self._nearest_cell_edge(cell_id, pick_point)
        if edge is None:
            return
        p1, p2, closest_point, pick_distance = edge
        length = self._distance(p1, p2)
        self.clear_selection(render=False)
        self._add_line_tube_actor(p1, p2, (1.0, 0.78, 0.05), opacity=0.85, radius_scale=0.0045)
        self._add_line_actor(p1, p2, (1.0, 0.05, 0.02), 5.0, self._selection_actors)
        self._add_sphere_marker(p1, (1.0, 0.05, 0.02), self._selection_actors, scale=0.009)
        self._add_sphere_marker(p2, (1.0, 0.05, 0.02), self._selection_actors, scale=0.009)
        circular = self._infer_circular_edge(pick_point)
        if circular:
            center = circular["center"]
            radius = float(circular["radius"])
            z = float(pick_point[2])
            circle = make_circle_polydata(radius, z=z, center=(float(center[0]), float(center[1])))
            self._add_tube_selection(circle, (0.0, 0.42, 1.0), opacity=0.70, radius_scale=0.003)
            self._add_polyline_selection(circle, (0.0, 0.20, 0.95), 4.5)
            self._add_sphere_marker((float(center[0]), float(center[1]), z), (0.0, 0.20, 0.95), self._selection_actors, scale=0.010)
        label = f"Edge | L {length:.2f} mm"
        if circular:
            label = f"{circular.get('name', 'Edge circular')} | dia {float(circular.get('diameter', 0.0) or 0.0):.2f} mm"
        self._add_selection_label(label, closest_point, (1.0, 0.12, 0.04))
        payload = {
            "type": "selection_edge",
            "cell_id": cell_id,
            "p1": p1,
            "p2": p2,
            "closest_point": closest_point,
            "mesh_segment_length": length,
            "pick_distance": pick_distance,
            "circular": circular,
        }
        self.selectionChanged.emit(payload)
        if self.measurement_enabled:
            self.measurementChanged.emit({"type": "edge_measurement", **payload})

    def _select_point(self, cell_id: int, point: tuple[float, float, float]) -> None:
        normal = self._cell_normal(cell_id)
        self.clear_selection(render=False)
        self._add_sphere_marker(point, (0.95, 0.16, 0.08), self._selection_actors, scale=0.011)
        self._add_selection_label("Ponto", point, (0.95, 0.16, 0.08))
        payload = {"type": "selection_point", "point": point, "cell_id": cell_id, "normal": normal}
        self.selectionChanged.emit(payload)
        if not self.measurement_enabled:
            return
        self._picked_points.append(point)
        self._add_sphere_marker(point, (0.90, 0.18, 0.12), self._measurement_actors, scale=0.008)
        if len(self._picked_points) == 1:
            self.measurementChanged.emit({"type": "point", "point": point, "cell_id": cell_id, "normal": normal})
        elif len(self._picked_points) == 2:
            measurement = Measurement(self._picked_points[0], self._picked_points[1])
            self._add_measurement_line(measurement)
            payload = measurement.to_dict()
            payload["type"] = "distance"
            payload["p1"] = measurement.p1
            payload["p2"] = measurement.p2
            payload["normal"] = normal
            self.measurementChanged.emit(payload)
            self._picked_points = []

    def _cell_points(self, cell_id: int) -> list[tuple[float, float, float]]:
        if self.polydata is None or cell_id < 0:
            return []
        cell = self.polydata.GetCell(cell_id)
        if cell is None:
            return []
        return [
            tuple(float(value) for value in self.polydata.GetPoint(cell.GetPointId(index)))
            for index in range(cell.GetNumberOfPoints())
        ]

    def _polydata_from_polygon(self, points: list[tuple[float, float, float]]):
        vtk_points = self.vtk.vtkPoints()
        polygon = self.vtk.vtkPolygon()
        polygon.GetPointIds().SetNumberOfIds(len(points))
        for index, point in enumerate(points):
            vtk_points.InsertNextPoint(*point)
            polygon.GetPointIds().SetId(index, index)
        cells = self.vtk.vtkCellArray()
        cells.InsertNextCell(polygon)
        polydata = self.vtk.vtkPolyData()
        polydata.SetPoints(vtk_points)
        polydata.SetPolys(cells)
        return polydata

    def _polygon_area(self, points: list[tuple[float, float, float]]) -> float:
        if len(points) < 3:
            return 0.0
        total = 0.0
        origin = points[0]
        for index in range(1, len(points) - 1):
            a = tuple(points[index][axis] - origin[axis] for axis in range(3))
            b = tuple(points[index + 1][axis] - origin[axis] for axis in range(3))
            cross = (
                a[1] * b[2] - a[2] * b[1],
                a[2] * b[0] - a[0] * b[2],
                a[0] * b[1] - a[1] * b[0],
            )
            total += 0.5 * math.sqrt(cross[0] ** 2 + cross[1] ** 2 + cross[2] ** 2)
        return total

    def _polygon_perimeter(self, points: list[tuple[float, float, float]]) -> float:
        if len(points) < 2:
            return 0.0
        return sum(self._distance(points[index], points[(index + 1) % len(points)]) for index in range(len(points)))

    def _centroid(self, points: list[tuple[float, float, float]]) -> tuple[float, float, float]:
        count = max(len(points), 1)
        return (
            sum(point[0] for point in points) / count,
            sum(point[1] for point in points) / count,
            sum(point[2] for point in points) / count,
        )

    def _points_bbox(self, points: list[tuple[float, float, float]]) -> dict[str, float]:
        if not points:
            return {}
        xs = [point[0] for point in points]
        ys = [point[1] for point in points]
        zs = [point[2] for point in points]
        return {
            "xmin": min(xs),
            "xmax": max(xs),
            "ymin": min(ys),
            "ymax": max(ys),
            "zmin": min(zs),
            "zmax": max(zs),
            "x": max(xs) - min(xs),
            "y": max(ys) - min(ys),
            "z": max(zs) - min(zs),
        }

    def _nearest_cell_edge(
        self,
        cell_id: int,
        pick_point: tuple[float, float, float],
    ) -> tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float], float] | None:
        points = self._cell_points(cell_id)
        if len(points) < 2:
            return None
        best: tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float], float] | None = None
        for index in range(len(points)):
            p1 = points[index]
            p2 = points[(index + 1) % len(points)]
            closest = self._closest_point_on_segment(pick_point, p1, p2)
            distance = self._distance(pick_point, closest)
            if best is None or distance < best[3]:
                best = (p1, p2, closest, distance)
        return best

    def _infer_circular_edge(self, point: tuple[float, float, float]) -> dict[str, Any] | None:
        if self._metadata.get("part_type") != "flange":
            return None
        params = self._metadata.get("parameters") or {}
        candidates: list[dict[str, Any]] = []

        def add_candidate(name: str, kind: str, center: tuple[float, float], radius: float, tolerance: float, index: int | None = None) -> None:
            if radius <= 0:
                return
            radial = math.hypot(point[0] - center[0], point[1] - center[1])
            error = abs(radial - radius)
            if error <= tolerance:
                candidates.append(
                    {
                        "name": name,
                        "kind": kind,
                        "center": (center[0], center[1], point[2]),
                        "radius": radius,
                        "diameter": radius * 2.0,
                        "circumference": 2.0 * math.pi * radius,
                        "radial_error": error,
                        "tolerance": tolerance,
                        "source": "metadata",
                        "index": index,
                    }
                )

        outer = params.get("outer_diameter", params.get("diameter"))
        if outer:
            outer_radius = float(outer) / 2.0
            add_candidate("Diametro externo", "outer_diameter", (0.0, 0.0), outer_radius, max(2.0, outer_radius * 0.08))

        center_hole = params.get("center_hole_diameter")
        if center_hole:
            center_radius = float(center_hole) / 2.0
            add_candidate("Furo central", "center_hole", (0.0, 0.0), center_radius, max(1.5, center_radius * 0.60))

        hole_diameter = float(params.get("hole_diameter", 0.0) or 0.0)
        for idx, center in enumerate(self._bolt_hole_centers()):
            add_candidate(
                f"Furo {idx + 1}",
                "bolt_circle_hole",
                (center[0], center[1]),
                hole_diameter / 2.0,
                max(2.0, hole_diameter * 0.35),
                idx + 1,
            )

        if not candidates:
            return None
        return sorted(candidates, key=lambda item: float(item["radial_error"]))[0]

    def _bolt_hole_centers(self) -> list[tuple[float, float]]:
        features = self._metadata.get("features") or []
        centers: list[tuple[float, float]] = []
        for feature in features:
            if feature.get("kind") != "bolt_circle_holes":
                continue
            positions = feature.get("positions") or []
            for position in positions:
                if isinstance(position, dict) and "x" in position and "y" in position:
                    centers.append((float(position["x"]), float(position["y"])))
            if centers:
                return centers
            params = feature.get("params") or {}
            count = int(feature.get("count", params.get("count", 0)) or 0)
            radius = float(feature.get("radius", params.get("radius", 0.0)) or 0.0)
            if count > 0 and radius > 0:
                return [
                    (radius * math.cos(2.0 * math.pi * index / count), radius * math.sin(2.0 * math.pi * index / count))
                    for index in range(count)
                ]
        params = self._metadata.get("parameters") or {}
        count = int(params.get("hole_count", 0) or 0)
        radius = float(params.get("bolt_circle_radius", 0.0) or 0.0)
        if count > 0 and radius > 0:
            return [
                (radius * math.cos(2.0 * math.pi * index / count), radius * math.sin(2.0 * math.pi * index / count))
                for index in range(count)
            ]
        return []

    def _closest_point_on_segment(
        self,
        point: tuple[float, float, float],
        p1: tuple[float, float, float],
        p2: tuple[float, float, float],
    ) -> tuple[float, float, float]:
        vx, vy, vz = p2[0] - p1[0], p2[1] - p1[1], p2[2] - p1[2]
        wx, wy, wz = point[0] - p1[0], point[1] - p1[1], point[2] - p1[2]
        length_sq = vx * vx + vy * vy + vz * vz
        if length_sq <= 1e-12:
            return p1
        t = max(0.0, min(1.0, (wx * vx + wy * vy + wz * vz) / length_sq))
        return p1[0] + t * vx, p1[1] + t * vy, p1[2] + t * vz

    def _distance(self, p1: tuple[float, float, float], p2: tuple[float, float, float]) -> float:
        return math.sqrt((p2[0] - p1[0]) ** 2 + (p2[1] - p1[1]) ** 2 + (p2[2] - p1[2]) ** 2)

    def _selection_span(self) -> float:
        bbox = self.stats.get("bbox", {})
        if isinstance(bbox, dict):
            return max(
                float(bbox.get("x", 1.0) or 1.0),
                float(bbox.get("y", 1.0) or 1.0),
                float(bbox.get("z", 1.0) or 1.0),
                1.0,
            )
        bounds = self.stats.get("bounds")
        if bounds:
            return max(
                float(bounds[1] - bounds[0]),
                float(bounds[3] - bounds[2]),
                float(bounds[5] - bounds[4]),
                1.0,
            )
        return 1.0

    def _bounds_label_position(self) -> tuple[float, float, float]:
        bounds = self.stats.get("bounds")
        span = self._selection_span()
        if bounds:
            return (
                float(bounds[0]),
                float(bounds[3]),
                float(bounds[5]) + span * 0.08,
            )
        return 0.0, 0.0, span * 0.08

    def _polydata_center(self, polydata) -> tuple[float, float, float]:
        if polydata is not None and polydata.GetNumberOfPoints() > 0:
            bounds = polydata.GetBounds()
            return (
                (float(bounds[0]) + float(bounds[1])) / 2.0,
                (float(bounds[2]) + float(bounds[3])) / 2.0,
                (float(bounds[4]) + float(bounds[5])) / 2.0,
            )
        return self._bounds_label_position()

    def _edge_label_position(self, edge: dict[str, Any]) -> tuple[float, float, float] | None:
        raw_points = edge.get("points") or []
        if isinstance(raw_points, dict):
            raw_points = raw_points.get("points") or []
        if raw_points:
            midpoint = raw_points[len(raw_points) // 2]
            return self._xyz_tuple(midpoint)
        curve = edge.get("curve") or {}
        return self._xyz_tuple(curve.get("center"))

    def _add_selection_label(
        self,
        text: str,
        position: tuple[float, float, float] | None,
        color: tuple[float, float, float],
    ) -> None:
        if position is None:
            position = self._bounds_label_position()
        span = self._selection_span()
        z_offset = max(span * 0.035, 0.8)
        vector_text = self.vtk.vtkVectorText()
        vector_text.SetText(str(text)[:96])
        mapper = self.vtk.vtkPolyDataMapper()
        mapper.SetInputConnection(vector_text.GetOutputPort())
        actor = self.vtk.vtkFollower()
        actor.SetMapper(mapper)
        actor.SetCamera(self.renderer.GetActiveCamera())
        scale = max(span * 0.012, 0.45)
        actor.SetScale(scale, scale, scale)
        actor.SetPosition(float(position[0]), float(position[1]), float(position[2]) + z_offset)
        actor.GetProperty().SetColor(*color)
        actor.GetProperty().SetAmbient(0.9)
        actor.GetProperty().SetDiffuse(0.2)
        self.renderer.AddActor(actor)
        self._selection_actors.append(actor)

    def _add_tube_selection(
        self,
        polydata,
        color: tuple[float, float, float],
        opacity: float = 0.75,
        radius_scale: float = 0.004,
    ) -> None:
        if polydata is None or polydata.GetNumberOfPoints() < 2:
            return
        tube = self.vtk.vtkTubeFilter()
        tube.SetInputData(polydata)
        tube.SetRadius(max(self._selection_span() * radius_scale, 0.10))
        tube.SetNumberOfSides(18)
        tube.CappingOn()
        mapper = self.vtk.vtkPolyDataMapper()
        mapper.SetInputConnection(tube.GetOutputPort())
        actor = self.vtk.vtkActor()
        actor.SetMapper(mapper)
        actor.GetProperty().SetColor(*color)
        actor.GetProperty().SetOpacity(opacity)
        actor.GetProperty().SetAmbient(0.25)
        actor.GetProperty().SetDiffuse(0.75)
        self.renderer.AddActor(actor)
        self._selection_actors.append(actor)

    def _add_line_tube_actor(
        self,
        p1: tuple[float, float, float],
        p2: tuple[float, float, float],
        color: tuple[float, float, float],
        opacity: float = 0.75,
        radius_scale: float = 0.004,
    ) -> None:
        line = self.vtk.vtkLineSource()
        line.SetPoint1(*p1)
        line.SetPoint2(*p2)
        line.Update()
        self._add_tube_selection(line.GetOutput(), color, opacity=opacity, radius_scale=radius_scale)

    def _add_polyline_selection(self, polydata, color: tuple[float, float, float], width: float) -> None:
        mapper = self.vtk.vtkPolyDataMapper()
        mapper.SetInputData(polydata)
        actor = self.vtk.vtkActor()
        actor.SetMapper(mapper)
        actor.GetProperty().SetColor(*color)
        actor.GetProperty().SetLineWidth(width)
        self.renderer.AddActor(actor)
        self._selection_actors.append(actor)

    def _add_line_actor(
        self,
        p1: tuple[float, float, float],
        p2: tuple[float, float, float],
        color: tuple[float, float, float],
        width: float,
        collection: list[Any],
    ) -> None:
        line = self.vtk.vtkLineSource()
        line.SetPoint1(*p1)
        line.SetPoint2(*p2)
        mapper = self.vtk.vtkPolyDataMapper()
        mapper.SetInputConnection(line.GetOutputPort())
        actor = self.vtk.vtkActor()
        actor.SetMapper(mapper)
        actor.GetProperty().SetColor(*color)
        actor.GetProperty().SetLineWidth(width)
        self.renderer.AddActor(actor)
        collection.append(actor)

    def _add_sphere_marker(
        self,
        point: tuple[float, float, float],
        color: tuple[float, float, float],
        collection: list[Any],
        scale: float = 0.008,
    ) -> None:
        bbox = self.stats.get("bbox", {})
        radius = max(max(float(bbox.get("x", 1.0) or 1.0), float(bbox.get("y", 1.0) or 1.0), float(bbox.get("z", 1.0) or 1.0)) * scale, 0.25)
        sphere = self.vtk.vtkSphereSource()
        sphere.SetCenter(*point)
        sphere.SetRadius(radius)
        sphere.Update()
        mapper = self.vtk.vtkPolyDataMapper()
        mapper.SetInputConnection(sphere.GetOutputPort())
        actor = self.vtk.vtkActor()
        actor.SetMapper(mapper)
        actor.GetProperty().SetColor(*color)
        self.renderer.AddActor(actor)
        collection.append(actor)

    def _cell_normal(self, cell_id: int) -> tuple[float, float, float] | None:
        if self.polydata is None or cell_id < 0:
            return None
        try:
            cell = self.polydata.GetCell(cell_id)
            if cell is None or cell.GetNumberOfPoints() < 3:
                return None
            points = []
            for index in range(3):
                point_id = cell.GetPointId(index)
                points.append(self.polydata.GetPoint(point_id))
            ax, ay, az = (points[1][i] - points[0][i] for i in range(3))
            bx, by, bz = (points[2][i] - points[0][i] for i in range(3))
            nx = ay * bz - az * by
            ny = az * bx - ax * bz
            nz = ax * by - ay * bx
            length = math.sqrt(nx * nx + ny * ny + nz * nz) or 1.0
            return nx / length, ny / length, nz / length
        except Exception:
            return None

    def _add_measurement_marker(self, point: tuple[float, float, float]) -> None:
        sphere = self.vtk.vtkSphereSource()
        sphere.SetCenter(*point)
        sphere.SetRadius(max(max(self.stats.get("bbox", {}).get("x", 1.0), self.stats.get("bbox", {}).get("y", 1.0)) * 0.008, 0.5))
        sphere.Update()
        mapper = self.vtk.vtkPolyDataMapper()
        mapper.SetInputConnection(sphere.GetOutputPort())
        actor = self.vtk.vtkActor()
        actor.SetMapper(mapper)
        actor.GetProperty().SetColor(0.90, 0.18, 0.12)
        self.renderer.AddActor(actor)
        self._measurement_actors.append(actor)

    def _add_measurement_line(self, measurement: Measurement) -> None:
        line = self.vtk.vtkLineSource()
        line.SetPoint1(*measurement.p1)
        line.SetPoint2(*measurement.p2)
        mapper = self.vtk.vtkPolyDataMapper()
        mapper.SetInputConnection(line.GetOutputPort())
        actor = self.vtk.vtkActor()
        actor.SetMapper(mapper)
        actor.GetProperty().SetColor(0.05, 0.32, 0.88)
        actor.GetProperty().SetLineWidth(3.0)
        self.renderer.AddActor(actor)
        self._measurement_actors.append(actor)

    def export_screenshot(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        window_to_image = self.vtk.vtkWindowToImageFilter()
        window_to_image.SetInput(self.render_window)
        window_to_image.Update()
        writer = self.vtk.vtkPNGWriter()
        writer.SetFileName(str(path))
        writer.SetInputConnection(window_to_image.GetOutputPort())
        writer.Write()
        return path

    def export_png(self, path: Path) -> Path:
        return self.export_screenshot(path)

    def render_scene(self) -> None:
        self.render_window.Render()

    def get_mesh_stats(self) -> dict[str, Any]:
        return dict(self.stats)
