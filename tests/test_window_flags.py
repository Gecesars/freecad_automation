from __future__ import annotations

from pathlib import Path


def test_main_window_does_not_use_forbidden_window_flags() -> None:
    source = (Path("app") / "ui_main.py").read_text(encoding="utf-8")
    forbidden = [
        "FramelessWindowHint",
        "CustomizeWindowHint",
        "WindowStaysOnTopHint",
        "SplashScreen",
        "Qt.Tool",
        "Qt.Popup",
        "showFullScreen",
    ]
    for token in forbidden:
        assert token not in source
    assert "WindowMinimizeButtonHint" in source
    assert "WindowMaximizeButtonHint" in source
    assert "WindowCloseButtonHint" in source


def test_gui_entrypoint_uses_maximized_show() -> None:
    source = (Path("app") / "main.py").read_text(encoding="utf-8")
    assert "window.showMaximized()" in source
    assert "window.showFullScreen()" not in source
