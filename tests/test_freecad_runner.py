from __future__ import annotations

from app import freecad_runner


def test_runner_handles_missing_freecad(monkeypatch, tmp_path) -> None:
    macro = tmp_path / "macro.py"
    macro.write_text("print('macro')\n", encoding="utf-8")
    monkeypatch.delenv("FREECAD_CMD", raising=False)
    monkeypatch.setenv("PATH", "")
    monkeypatch.setattr(freecad_runner, "DEFAULT_FREECAD_CANDIDATES", [])
    monkeypatch.setattr(freecad_runner, "find_freecad_executable", lambda: None)
    monkeypatch.setattr(freecad_runner, "discover_freecad_binaries", lambda: [])
    result = freecad_runner.run_macro(macro, output_dir=tmp_path, timeout=1)
    assert not result.ok
    assert "Macro gerada com sucesso" in result.message
    assert result.command == ()
