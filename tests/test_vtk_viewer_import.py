from __future__ import annotations

from pathlib import Path

from app.viewer3d.vtk_lod import read_polydata, vtk_available


def _write_cube_stl(path: Path) -> None:
    import vtkmodules.all as vtk

    cube = vtk.vtkCubeSource()
    cube.SetXLength(10.0)
    cube.SetYLength(20.0)
    cube.SetZLength(5.0)
    cube.Update()
    triangle = vtk.vtkTriangleFilter()
    triangle.SetInputConnection(cube.GetOutputPort())
    triangle.Update()
    writer = vtk.vtkSTLWriter()
    writer.SetFileName(str(path))
    writer.SetInputConnection(triangle.GetOutputPort())
    writer.Write()


def test_vtk_import_reads_polydata_bounds(tmp_path) -> None:
    assert vtk_available()
    stl_path = tmp_path / "cube.stl"
    _write_cube_stl(stl_path)
    polydata = read_polydata(stl_path)
    assert polydata.GetNumberOfPoints() > 0
    assert polydata.GetNumberOfCells() > 0
    bounds = polydata.GetBounds()
    assert bounds[1] > bounds[0]
    assert bounds[3] > bounds[2]
    assert bounds[5] > bounds[4]
