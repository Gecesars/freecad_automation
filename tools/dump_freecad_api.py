from __future__ import annotations

import inspect
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "data" / "rag" / "api_dump"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def safe_dir(module_name):
    try:
        module = __import__(module_name)
        return sorted(name for name in dir(module) if not name.startswith("__"))
    except Exception as exc:
        return {"error": str(exc)}


def doc_map(module_name, limit=250):
    try:
        module = __import__(module_name)
    except Exception as exc:
        return {"error": str(exc)}
    result = {}
    for name in sorted(dir(module))[:limit]:
        if name.startswith("__"):
            continue
        try:
            obj = getattr(module, name)
            doc = inspect.getdoc(obj) or ""
            signature = ""
            try:
                signature = str(inspect.signature(obj))
            except Exception:
                pass
            result[name] = {"signature": signature, "doc": doc[:1200]}
        except Exception as exc:
            result[name] = {"error": str(exc)}
    return result


def main():
    import FreeCAD as App

    modules = ["FreeCAD", "Part", "Mesh", "Draft", "Import", "ImportGui", "FreeCADGui"]
    payload = {
        "version": App.Version(),
        "modules": {module: safe_dir(module) for module in modules},
        "docstrings": {module: doc_map(module) for module in modules},
        "workbenches": [],
        "import_export": {},
    }
    try:
        import FreeCADGui as Gui

        payload["workbenches"] = sorted(Gui.listWorkbenches().keys())
    except Exception as exc:
        payload["workbenches_error"] = str(exc)
    json_path = OUT_DIR / "freecad_api_dump.json"
    md_path = OUT_DIR / "freecad_api_dump.md"
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    lines = ["# FreeCAD API Dump", "", f"Version: `{payload['version']}`", ""]
    for module, names in payload["modules"].items():
        lines.extend([f"## {module}", ""])
        if isinstance(names, dict):
            lines.append(f"Error: {names.get('error')}")
        else:
            lines.append(", ".join(names[:500]))
        lines.append("")
    md_path.write_text("\n".join(lines), encoding="utf-8")
    print(json_path)
    print(md_path)


if __name__ == "__main__":
    main()
