from __future__ import annotations

from app.prompt_parser import parse_prompt


def test_parse_plate_with_words_material_slot_and_corner_holes() -> None:
    spec = parse_prompt(
        "Crie uma placa de aluminio 120x80x6 mm com quatro furos de 6 mm nos cantos e um rasgo central de 40x12 mm."
    )
    assert spec.part_type == "plate"
    assert spec.material == "aluminium"
    assert spec.dimensions["length"] == 120
    assert spec.dimensions["width"] == 80
    assert spec.dimensions["thickness"] == 6
    holes = spec.feature("holes")
    assert holes is not None
    assert holes.params["count"] == 4
    assert holes.params["placement"] == "corners"
    slot = spec.feature("slot")
    assert slot is not None
    assert slot.params["length"] == 40
    assert slot.params["width"] == 12


def test_parse_flange() -> None:
    spec = parse_prompt("flange circular de 100 mm de diametro, 10 mm de espessura, furo central de 30 mm e 6 furos de 8 mm")
    assert spec.part_type == "flange"
    assert spec.dimensions["diameter"] == 100
    assert spec.dimensions["thickness"] == 10
    assert spec.dimensions["center_hole"] == 30
    holes = spec.feature("holes")
    assert holes is not None
    assert holes.params["count"] == 6
    assert holes.params["diameter"] == 8


def test_parse_flange_with_only_center_hole_does_not_add_bolt_hole() -> None:
    spec = parse_prompt("flange circular de 30 mm de diametro, 10 mm de espessura e um furo central de 12 mm")
    assert spec.part_type == "flange"
    assert spec.dimensions["diameter"] == 30
    assert spec.dimensions["thickness"] == 10
    assert spec.dimensions["center_hole"] == 12
    assert "hole_diameter" not in spec.dimensions
    assert spec.feature("center_hole") is not None
    assert spec.feature("holes") is None


def test_parse_cylinder_axis() -> None:
    spec = parse_prompt("eixo de aco com 20 mm de diametro e 120 mm de comprimento com chanfro")
    assert spec.part_type == "cylinder"
    assert spec.material == "steel"
    assert spec.dimensions["diameter"] == 20
    assert spec.dimensions["length"] == 120
    assert spec.feature("chamfer") is not None


def test_parse_box_open_wall() -> None:
    spec = parse_prompt("caixa aberta de 100x80x40 mm com parede de 3 mm")
    assert spec.part_type == "box"
    assert spec.dimensions["length"] == 100
    assert spec.dimensions["width"] == 80
    assert spec.dimensions["height"] == 40
    assert spec.dimensions["wall"] == 3
    assert spec.feature("hollow") is not None
