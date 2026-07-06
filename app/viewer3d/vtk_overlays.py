from __future__ import annotations

import math
from typing import Iterable


def make_circle_polydata(radius: float, z: float = 0.0, segments: int = 160, center: tuple[float, float] = (0.0, 0.0)):
    import vtkmodules.all as vtk

    points = vtk.vtkPoints()
    lines = vtk.vtkCellArray()
    previous_id = None
    first_id = None
    for idx in range(segments):
        angle = 2.0 * math.pi * idx / segments
        point_id = points.InsertNextPoint(center[0] + radius * math.cos(angle), center[1] + radius * math.sin(angle), z)
        if first_id is None:
            first_id = point_id
        if previous_id is not None:
            line = vtk.vtkLine()
            line.GetPointIds().SetId(0, previous_id)
            line.GetPointIds().SetId(1, point_id)
            lines.InsertNextCell(line)
        previous_id = point_id
    if first_id is not None and previous_id is not None:
        line = vtk.vtkLine()
        line.GetPointIds().SetId(0, previous_id)
        line.GetPointIds().SetId(1, first_id)
        lines.InsertNextCell(line)
    polydata = vtk.vtkPolyData()
    polydata.SetPoints(points)
    polydata.SetLines(lines)
    return polydata


def make_points_polydata(points_iter: Iterable[tuple[float, float, float]]):
    import vtkmodules.all as vtk

    points = vtk.vtkPoints()
    vertices = vtk.vtkCellArray()
    for point in points_iter:
        point_id = points.InsertNextPoint(*point)
        vertices.InsertNextCell(1)
        vertices.InsertCellPoint(point_id)
    polydata = vtk.vtkPolyData()
    polydata.SetPoints(points)
    polydata.SetVerts(vertices)
    return polydata
