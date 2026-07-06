from __future__ import annotations

from app.macro_generator import MacroGenerator
from app.prompt_parser import parse_prompt


def test_macro_metadata_contains_parameters_features_shape_and_files(tmp_path) -> None:
    spec = parse_prompt("flange redondo de 100mm com 8 furos de 12mm num raio de 30mm espessura de 12mm")
    design = MacroGenerator(macros_dir=tmp_path / "macros", output_dir=tmp_path / "outputs", use_deepseek=False).generate(spec)
    code = design.macro_code
    assert '"units": "mm"' in code
    assert '"part_type": spec_payload.get("part_type")' in code
    assert '"parameters": parameters' in code
    assert '"features": feature_payload' in code
    assert '"shape": shape_payload' in code
    assert '"files": {' in code
    assert "positions" in code
    assert "diameter_pcd" in code
    assert "topology_metadata(shape, metadata, topology_path, canonical_topology_path)" in code
    assert "face_mesh_payload" in code
    assert "edge_points_payload" in code
