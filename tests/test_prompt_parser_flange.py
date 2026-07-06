from __future__ import annotations

from app.geometry_validator import validate_geometry
from app.prompt_parser import parse_prompt


def test_flange_hole_diameter_dia_5mm() -> None:
    prompt = "flange redondo de latão com diametro de 60mm 8 furos passantes dia 5mm num raio de 39mm e um furo central de 20mm"
    parsed = parse_prompt(prompt)
    assert parsed["part_type"] == "flange"
    assert parsed["material"] == "brass"
    assert parsed["dimensions"]["outer_diameter"] == 60.0
    assert parsed["dimensions"]["hole_diameter"] == 5.0
    assert parsed["dimensions"]["hole_count"] == 8
    assert parsed["dimensions"]["center_hole_diameter"] == 20.0
    assert parsed["dimensions"]["bolt_circle_radius"] == 39.0
    assert "Diametro dos furos nao informado" not in "\n".join(parsed["assumptions"])


def test_flange_radius_39_invalid_for_outer_60() -> None:
    parsed = parse_prompt("flange redondo diametro 60mm com 8 furos dia 5mm num raio de 39mm")
    result = validate_geometry(parsed)
    assert result["valid"] is False
    assert result["error_type"] == "bolt_circle_outside_part"


def test_flange_pcd_39_valid_for_outer_60() -> None:
    parsed = parse_prompt("flange redondo diametro 60mm com 8 furos dia 5mm no diametro primitivo de 39mm")
    result = validate_geometry(parsed)
    assert result["valid"] is True
    assert parsed["dimensions"]["bolt_circle_diameter"] == 39.0
    assert parsed["dimensions"]["bolt_circle_radius"] == 19.5


def test_flange_holes_on_plain_diameter_context() -> None:
    parsed = parse_prompt("crie um flange circular de diametro 45 com 8 furos de 4mm num diametro de 30mm espesura de 10mm")
    assert parsed["part_type"] == "flange"
    assert parsed["dimensions"]["outer_diameter"] == 45.0
    assert parsed["dimensions"]["hole_count"] == 8
    assert parsed["dimensions"]["hole_diameter"] == 4.0
    assert parsed["dimensions"]["bolt_circle_diameter"] == 30.0
    assert parsed["dimensions"]["bolt_circle_radius"] == 15.0
    assert parsed["dimensions"]["thickness"] == 10.0
    assert "center_hole" not in parsed["dimensions"]
    assert not parsed["assumptions"]
    assert validate_geometry(parsed)["valid"] is True


def test_flange_with_typos_radius_and_thread_keeps_hole_diameter() -> None:
    parsed = parse_prompt("crie um flange redondo de diametro 45mm com 8 furus num raio de 13mm cada furo com dia 4mm rosda m5")
    assert parsed["part_type"] == "flange"
    assert parsed["dimensions"]["outer_diameter"] == 45.0
    assert parsed["dimensions"]["hole_count"] == 8
    assert parsed["dimensions"]["hole_diameter"] == 4.0
    assert parsed["dimensions"]["bolt_circle_radius"] == 13.0
    assert parsed["dimensions"]["bolt_circle_diameter"] == 26.0
    assert parsed["dimensions"]["thread_nominal_diameter"] == 5.0
    holes = parsed.feature("bolt_circle_holes")
    assert holes is not None
    assert holes.params["thread"] == "M5"
    assert validate_geometry(parsed)["valid"] is True


def test_flange_outer_diameter_not_overwritten_by_late_ambiguous_diameter() -> None:
    parsed = parse_prompt(
        "flange redondo de 80mm com 8 furos de 10 mm num raio de 20mm "
        "com diametro de 8mm espessura de 10mm"
    )
    assert parsed["part_type"] == "flange"
    assert parsed["dimensions"]["outer_diameter"] == 80.0
    assert parsed["dimensions"]["diameter"] == 80.0
    assert parsed["dimensions"]["hole_count"] == 8
    assert parsed["dimensions"]["hole_diameter"] == 10.0
    assert parsed["dimensions"]["bolt_circle_radius"] == 20.0
    assert parsed["dimensions"]["bolt_circle_diameter"] == 40.0
    assert parsed["dimensions"]["thickness"] == 10.0
    assert any("8 mm" in warning and "ambiguo" in warning for warning in parsed["warnings"])
    assert validate_geometry(parsed)["valid"] is True


def test_flange_typo_flage_uses_circular_flange_not_default_plate() -> None:
    parsed = parse_prompt(
        "flage redondo com 100mm diametro 8 furos num raio de 30mm "
        "com diametro de 12mm espessura de 12mm"
    )
    assert parsed["part_type"] == "flange"
    assert parsed["dimensions"]["outer_diameter"] == 100.0
    assert parsed["dimensions"]["diameter"] == 100.0
    assert parsed["dimensions"]["hole_count"] == 8
    assert parsed["dimensions"]["hole_diameter"] == 12.0
    assert parsed["dimensions"]["bolt_circle_radius"] == 30.0
    assert parsed["dimensions"]["bolt_circle_diameter"] == 60.0
    assert parsed["dimensions"]["thickness"] == 12.0
    assert "length" not in parsed["dimensions"]
    assert "width" not in parsed["dimensions"]
    assert "Tipo nao identificado" not in "\n".join(parsed["assumptions"])
    holes = parsed.feature("bolt_circle_holes")
    assert holes is not None
    assert holes.params["placement"] == "bolt_circle"
    assert holes.params["radius"] == 30.0
    assert validate_geometry(parsed)["valid"] is True
