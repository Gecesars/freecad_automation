from __future__ import annotations

from app.models import PartSpec


BASE_TERMS = "FreeCAD Python Part Shape isValid BoundBox App.newDocument recompute Part.export Mesh.export doc.saveAs STEP STL FCStd"


def build_technical_rag_query(spec: PartSpec) -> str:
    feature_terms = " ".join(spec.feature_names())
    if spec.part_type == "flange":
        return (
            f"{BASE_TERMS} makeCylinder cylinder cut boolean flange circular plate "
            f"center hole bolt circle holes export {feature_terms}"
        )
    if spec.part_type == "plate":
        return f"{BASE_TERMS} makeBox plate holes cut slot rectangular rounded export {feature_terms}"
    if spec.part_type == "box":
        return f"{BASE_TERMS} makeBox hollow box wall thickness shell cut export {feature_terms}"
    if spec.part_type == "cylinder":
        return f"{BASE_TERMS} makeCylinder cylinder shaft chamfer fillet export {feature_terms}"
    if spec.part_type == "l_bracket":
        return f"{BASE_TERMS} makeBox fuse cut l bracket ribs holes export {feature_terms}"
    return f"{BASE_TERMS} makeBox makeCylinder cut fuse export {feature_terms}"
