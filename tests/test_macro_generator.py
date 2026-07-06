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
