from __future__ import annotations

from pathlib import Path

from app.viewer3d.vtk_lod import prepare_mesh_lod, vtk_available


def _write_sample_stl(path: Path) -> None:
    import vtkmodules.all as vtk

    source = vtk.vtkSphereSource()
    source.SetRadius(10.0)
    source.SetThetaResolution(16)
    source.SetPhiResolution(8)
    source.Update()
    writer = vtk.vtkSTLWriter()
    writer.SetFileName(str(path))
    writer.SetInputConnection(source.GetOutputPort())
    writer.Write()


def test_prepare_mesh_lod_reads_vtk_stl(tmp_path) -> None:
    assert vtk_available()
    stl_path = tmp_path / "sample.stl"
    _write_sample_stl(stl_path)
    info = prepare_mesh_lod(stl_path, tmp_path)
    assert info.ok
    assert info.display_path is not None
    assert info.points > 0
    assert info.triangles > 0
    assert info.original_points == info.points
    assert info.original_triangles == info.triangles
    assert info.bbox is not None
    assert info.bbox["x"] > 0
