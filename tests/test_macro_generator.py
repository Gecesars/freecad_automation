from __future__ import annotations

import py_compile

from app.macro_generator import MacroGenerator
from app.prompt_parser import parse_prompt


def test_macro_generation_compiles(tmp_path) -> None:
    spec = parse_prompt("placa 120x80x6 mm com quatro furos de 6 mm nos cantos e rasgo central de 40x12 mm")
    design = MacroGenerator(
        macros_dir=tmp_path / "macros",
        output_dir=tmp_path / "outputs",
        use_deepseek=False,
    ).generate(spec)
    py_compile.compile(str(design.macro_path), doraise=True)
    assert "Part.makeBox(120, 80, 6" in design.macro_code
    assert "slot_length = 40" in design.macro_code
    assert design.macro_path.exists()


def test_macro_generation_applies_cad_ops(tmp_path) -> None:
    spec = parse_prompt("placa 100x80x6 [CAD_OP subtract_cylinder diameter=8 height=10 x=50 y=40 z=-1 axis=z]")
    design = MacroGenerator(
        macros_dir=tmp_path / "macros",
        output_dir=tmp_path / "outputs",
        use_deepseek=False,
    ).generate(spec)
    py_compile.compile(str(design.macro_path), doraise=True)
    assert "Part.makeCylinder(4" in design.macro_code
    assert "shape = apply_cut(shape, cad_tool_1" in design.macro_code
    assert "PromptForge_Project" in design.macro_code
    assert "Final_GeneratedPart" in design.macro_code
