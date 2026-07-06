from __future__ import annotations

import re
from typing import Iterable

from app.models import Feature, PartSpec
from app.utils import format_mm, normalize_text

NUMBER = r"([0-9]+(?:[,.][0-9]+)?)"
UNIT = r"\s*(mm|milimetros|milimetro|cm|centimetros|centimetro|m|metros|metro)?"

NUMBER_WORDS = {
    "um": 1,
    "uma": 1,
    "dois": 2,
    "duas": 2,
    "tres": 3,
    "quatro": 4,
    "cinco": 5,
    "seis": 6,
    "sete": 7,
    "oito": 8,
    "nove": 9,
    "dez": 10,
    "onze": 11,
    "doze": 12,
}

MATERIALS = {
    "aluminio": "aluminium",
    "aluminum": "aluminium",
    "aco inox": "stainless steel",
    "inox": "stainless steel",
    "aco": "steel",
    "steel": "steel",
    "latao": "brass",
    "brass": "brass",
    "plastico": "plastic",
    "plastic": "plastic",
    "cobre": "copper",
    "copper": "copper",
    "nylon": "nylon",
}

MATERIAL_COLORS = {
    "aluminium": (0.72, 0.74, 0.76),
    "steel": (0.42, 0.45, 0.47),
    "stainless steel": (0.62, 0.64, 0.66),
    "brass": (0.82, 0.62, 0.22),
    "plastic": (0.08, 0.16, 0.24),
    "copper": (0.78, 0.34, 0.16),
    "nylon": (0.92, 0.92, 0.86),
}


def to_mm(value: str, unit: str | None) -> float:
    number = float(value.replace(",", "."))
    unit = (unit or "mm").lower()
    if unit.startswith("cm") or unit.startswith("centimetro"):
        return number * 10.0
    if unit in {"m", "metro", "metros"}:
        return number * 1000.0
    return number


def _contains_any(text: str, words: Iterable[str]) -> bool:
    return any(word in text for word in words)


def _number_token_to_int(token: str) -> int | None:
    token = normalize_text(token).strip()
    if token.isdigit():
        return int(token)
    return NUMBER_WORDS.get(token)


def _extract_box_dimensions(text: str) -> tuple[float, float, float] | None:
    pattern = rf"{NUMBER}{UNIT}\s*[xX*]\s*{NUMBER}{UNIT}\s*[xX*]\s*{NUMBER}{UNIT}"
    match = re.search(pattern, text)
    if not match:
        return None
    groups = match.groups()
    last_unit = groups[5] or groups[3] or groups[1] or "mm"
    return (
        to_mm(groups[0], groups[1] or last_unit),
        to_mm(groups[2], groups[3] or last_unit),
        to_mm(groups[4], groups[5] or last_unit),
    )


def _extract_pair_after(text: str, keywords: tuple[str, ...]) -> tuple[float, float] | None:
    keyword_pattern = "|".join(re.escape(keyword) for keyword in keywords)
    pattern = rf"(?:{keyword_pattern})[^\n.,;:]*?{NUMBER}{UNIT}\s*[xX*]\s*{NUMBER}{UNIT}"
    match = re.search(pattern, text)
    if not match:
        return None
    unit = match.group(4) or match.group(2) or "mm"
    return to_mm(match.group(1), match.group(2) or unit), to_mm(match.group(3), match.group(4) or unit)


def _extract_named_dimension(text: str, aliases: tuple[str, ...]) -> float | None:
    alias_pattern = "|".join(re.escape(alias) for alias in aliases)
    patterns = [
        rf"(?:{alias_pattern})\s*(?:de|com|=|:)?\s*{NUMBER}{UNIT}",
        rf"{NUMBER}{UNIT}\s*(?:de\s*)?(?:{alias_pattern})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return to_mm(match.group(1), match.group(2))
    return None


HOLE_TERMS = "furos|furo|furus|furu|holes|hole|parafusos|parafuso"
SLOT_TERMS = "rasgo|slot|oblongo|fenda|ranhura"
FLANGE_TERMS = "flanges?|flages?"


def _first_hole_term_start(text: str) -> int:
    match = re.search(rf"\b(?:{HOLE_TERMS})\b", text)
    return match.start() if match else len(text)


def _first_feature_term_start(text: str) -> int:
    starts = [
        match.start()
        for match in re.finditer(rf"\b(?:{HOLE_TERMS}|{SLOT_TERMS}|chanfro|chamfer|arredond|fillet|nervura|reforco|rib)\b", text)
    ]
    return min(starts) if starts else len(text)


def _part_dimension_text(text: str) -> str:
    start = _first_feature_term_start(text)
    return text[:start] if start < len(text) else text


def _normalize_unit_typos(text: str) -> str:
    return re.sub(r"(?<=\d)\s*m{3,}\b", "mm", text)


def _strip_cad_operation_directives(prompt: str) -> str:
    return re.sub(r"\[CAD_OP\b.*?\]", " ", prompt, flags=re.IGNORECASE | re.DOTALL)


def _extract_plate_pair_dimensions(text: str) -> tuple[float, float] | None:
    patterns = [
        rf"\b(?:placa|chapa|base|plate)[^\n.,;:]{{0,90}}?{NUMBER}{UNIT}\s*[xX*]\s*{NUMBER}{UNIT}",
        rf"\b{NUMBER}{UNIT}\s*[xX*]\s*{NUMBER}{UNIT}\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        groups = match.groups()
        unit = groups[-1] or groups[-3] or "mm"
        return to_mm(groups[-4], groups[-3] or unit), to_mm(groups[-2], groups[-1] or unit)
    square = re.search(rf"\bquadrad[ao]\s*(?:de|com)?\s*{NUMBER}{UNIT}\b", text)
    if square:
        value = to_mm(square.group(1), square.group(2))
        return value, value
    return None


def _extract_flange_outer_diameter(text: str) -> float | None:
    hole_start = _first_hole_term_start(text)
    before_holes = text[:hole_start]
    patterns = [
        rf"\b(?:{FLANGE_TERMS})\s+(?:redondo|circular)?\s*(?:de|com)?\s*{NUMBER}{UNIT}\b",
        rf"\b(?:{FLANGE_TERMS})[^\n.,;:]{{0,80}}?\bdiametro\s*(?:externo|total|do flange|da flange)?\s*(?:de|com|=|:)?\s*{NUMBER}{UNIT}",
        rf"\b(?:{FLANGE_TERMS})[^\n.,;:]{{0,80}}?{NUMBER}{UNIT}\s*(?:de\s*)?diametro\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, before_holes)
        if match:
            groups = match.groups()
            return to_mm(groups[-2], groups[-1])
    return None


def _ambiguous_diameters_after_holes(text: str, used_values: set[float]) -> list[float]:
    tail = text[_first_hole_term_start(text) :]
    values: list[float] = []
    for match in re.finditer(rf"\bdiametro\s*(?:de|com|=|:)?\s*{NUMBER}{UNIT}", tail):
        value = to_mm(match.group(1), match.group(2))
        if all(abs(value - used) > 1e-6 for used in used_values):
            values.append(value)
    return values


def _extract_thread(text: str) -> str | None:
    match = re.search(r"\b(?:rosca|rosda|roscado|thread)\s*m\s*([0-9]+(?:[,.][0-9]+)?)\b|\bm\s*([0-9]+(?:[,.][0-9]+)?)\b", text)
    if not match:
        return None
    number = float((match.group(1) or match.group(2)).replace(",", "."))
    text_value = f"{number:g}"
    return f"M{text_value}"


def _extract_slot_dimensions(text: str) -> tuple[float | None, float | None]:
    pair = _extract_pair_after(text, tuple(SLOT_TERMS.split("|")))
    slot_match = re.search(rf"\b(?:{SLOT_TERMS})\b", text)
    if not slot_match:
        return (pair[0], pair[1]) if pair else (None, None)
    tail = text[slot_match.end() : slot_match.end() + 180]
    length = _extract_named_dimension(tail, ("comprimento", "length", "longo"))
    width = _extract_named_dimension(tail, ("largura", "width"))
    if pair and length is None and width is None:
        return pair
    return length, width


def _parse_cad_operation_features(prompt: str) -> list[Feature]:
    features: list[Feature] = []
    for match in re.finditer(r"\[CAD_OP\s+([a-zA-Z_][a-zA-Z0-9_-]*)(.*?)\]", prompt, flags=re.DOTALL):
        op = match.group(1).strip().lower().replace("-", "_")
        raw_params = match.group(2)
        params: dict[str, object] = {"op": op}
        for key, raw_value in re.findall(r"([a-zA-Z_][a-zA-Z0-9_]*)=('[^']*'|\"[^\"]*\"|[^\s\]]+)", raw_params):
            value = raw_value.strip().strip("'\"")
            try:
                params[key] = float(value.replace(",", "."))
            except ValueError:
                params[key] = value
        features.append(Feature("cad_op", params))
    return features


def _extract_hole_diameter(text: str) -> float | None:
    word_pattern = "|".join(NUMBER_WORDS)
    patterns = [
        rf"\b(?:[1-9][0-9]?|{word_pattern})\s*(?:{HOLE_TERMS})\s*(?:passantes?\s*)?(?:dia|diametro|diameter|de|com|=|:)?\s*{NUMBER}{UNIT}",
        rf"(?:cada\s*)?(?:{HOLE_TERMS})\s*(?:passantes?\s*)?(?:dia|diametro|diameter|de|com|=|:)?\s*{NUMBER}{UNIT}",
        rf"(?:diametro dos furos|diametro do furo|diametro dos parafusos|hole diameter|dia dos furos|dia do furo)\s*(?:de|=|:)?\s*{NUMBER}{UNIT}",
        rf"(?:{HOLE_TERMS})[^\n.,;:]{{0,80}}?\b(?:dia|diametro|diameter)\s*(?:de|=|:)?\s*{NUMBER}{UNIT}",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            groups = match.groups()
            return to_mm(groups[-2], groups[-1])
    metric = re.search(r"\bm\s*([0-9]+(?:[,.][0-9]+)?)\b", text)
    if metric:
        return float(metric.group(1).replace(",", "."))
    return None


def _extract_bolt_circle(text: str, part_type: str, hole_count: int) -> tuple[float | None, float | None]:
    diameter_patterns = [
        rf"(?:diametro primitivo|diametro do circulo primitivo|circulo primitivo|pcd|bolt circle)\s*(?:de|com|=|:)?\s*{NUMBER}{UNIT}",
        rf"{NUMBER}{UNIT}\s*(?:de\s*)?(?:diametro primitivo|circulo primitivo|pcd|bolt circle)",
        rf"(?:{HOLE_TERMS})[^\n.,;:]{{0,90}}?(?:num|no|em um|em|sobre um)\s+diametro\s*(?:de|com|=|:)?\s*{NUMBER}{UNIT}",
    ]
    for pattern in diameter_patterns:
        match = re.search(pattern, text)
        if match:
            diameter = to_mm(match.group(1), match.group(2))
            return diameter, diameter / 2.0

    if part_type != "flange" or not hole_count:
        return None, None

    radius_patterns = [
        rf"(?:raio dos furos|raio da furacao|raio de furacao|raio de fixacao|num raio|no raio|em um raio|raio)\s*(?:de|com|=|:)?\s*{NUMBER}{UNIT}",
        rf"{NUMBER}{UNIT}\s*(?:de\s*)?(?:raio dos furos|raio da furacao|raio de furacao|raio de fixacao)",
    ]
    for pattern in radius_patterns:
        match = re.search(pattern, text)
        if match:
            radius = to_mm(match.group(1), match.group(2))
            return radius * 2.0, radius
    return None, None


def _sync_dimension_aliases(dimensions: dict[str, float]) -> None:
    if "diameter" in dimensions:
        dimensions.setdefault("outer_diameter", dimensions["diameter"])
    if "outer_diameter" in dimensions:
        dimensions.setdefault("diameter", dimensions["outer_diameter"])
    if "center_hole" in dimensions:
        dimensions.setdefault("center_hole_diameter", dimensions["center_hole"])
    if "center_hole_diameter" in dimensions:
        dimensions.setdefault("center_hole", dimensions["center_hole_diameter"])
    if "bolt_circle" in dimensions:
        dimensions.setdefault("bolt_circle_diameter", dimensions["bolt_circle"])
        dimensions.setdefault("bolt_circle_radius", dimensions["bolt_circle"] / 2.0)
    if "bolt_circle_diameter" in dimensions:
        dimensions.setdefault("bolt_circle", dimensions["bolt_circle_diameter"])
        dimensions.setdefault("bolt_circle_radius", dimensions["bolt_circle_diameter"] / 2.0)
    if "bolt_circle_radius" in dimensions:
        dimensions.setdefault("bolt_circle_diameter", dimensions["bolt_circle_radius"] * 2.0)
        dimensions.setdefault("bolt_circle", dimensions["bolt_circle_radius"] * 2.0)


def _extract_hole_count(text: str) -> int:
    word_pattern = "|".join(NUMBER_WORDS)
    pattern = rf"\b([1-9][0-9]?|{word_pattern})\s*(?:{HOLE_TERMS})\b"
    for match in re.finditer(pattern, text):
        after = text[match.end() : match.end() + 30]
        if re.search(r"\s+(central|interno|interna|no centro|centrado)", after):
            continue
        value = _number_token_to_int(match.group(1))
        if value is not None:
            if "cada aba" in text and value <= 6:
                return value * 2
            return value
    central_only = re.search(r"\bfuro\s+(central|interno)\b|\bdiametro interno\b|\bmiolo\b", text)
    has_other_hole_terms = re.search(r"\b(furos|furus|holes|parafusos|bolt|fixacao|fixação)\b", text)
    if central_only and not has_other_hole_terms:
        return 0
    if _contains_any(text, ("furo", "furos", "furus", "furu", "hole", "holes", "parafuso", "m5", "m6", "m8")):
        return 1
    return 0


def _extract_material(text: str) -> str | None:
    for source, normalized in MATERIALS.items():
        if source in text:
            return normalized
    return None


def _detect_part_type(text: str) -> tuple[str, list[str]]:
    assumptions: list[str] = []
    if re.search(rf"\b(?:{FLANGE_TERMS})\b", text) or "disco com furos" in text:
        if re.search(r"\bflage[s]?\b", text) and not re.search(r"\bflange[s]?\b", text):
            assumptions.append("Interpretando 'flage' como flange.")
        return "flange", assumptions
    if _contains_any(text, ("suporte em l", "cantoneira", "bracket", "mao francesa")):
        return "l_bracket", assumptions
    if _contains_any(text, ("eixo", "cilindro", "pino", "cylinder", "shaft")):
        return "cylinder", assumptions
    if _contains_any(text, ("caixa", "box", "case", "carcaca")):
        return "box", assumptions
    if _contains_any(text, ("placa", "chapa", "base", "plate")):
        return "plate", assumptions
    assumptions.append("Tipo nao identificado; usando placa parametrica como base.")
    return "plate", assumptions


def parse_prompt(prompt: str) -> PartSpec:
    prompt = prompt.strip()
    if not prompt:
        raise ValueError("Digite um prompt descrevendo a peca.")

    natural_prompt = _strip_cad_operation_directives(prompt)
    text = _normalize_unit_typos(normalize_text(natural_prompt))
    dimension_text = _part_dimension_text(text)
    part_type, assumptions = _detect_part_type(text)
    warnings: list[str] = []
    dimensions: dict[str, float] = {}
    features: list[Feature] = []
    material = _extract_material(text)
    flange_outer_diameter = _extract_flange_outer_diameter(text) if part_type == "flange" else None

    features.extend(_parse_cad_operation_features(prompt))

    box_dims = _extract_box_dimensions(dimension_text)
    if box_dims:
        dimensions["length"], dimensions["width"], dimensions["height"] = box_dims
    elif part_type == "plate":
        plate_pair = _extract_plate_pair_dimensions(dimension_text)
        if plate_pair:
            dimensions["length"], dimensions["width"] = plate_pair
    if flange_outer_diameter is not None:
        dimensions["diameter"] = flange_outer_diameter
        dimensions["outer_diameter"] = flange_outer_diameter

    named_aliases = {
        "length": ("comprimento", "longo", "length", "base"),
        "width": ("largura", "width"),
        "height": ("altura", "height", "alto"),
        "thickness": ("espessura", "espesura", "thickness", "grossura"),
        "diameter": ("diametro externo", "diametro", "diameter", "externo"),
        "center_hole": ("furo central", "diametro interno", "furo interno", "miolo"),
        "bolt_circle": ("diametro primitivo", "circulo primitivo", "pcd", "bolt circle"),
        "wall": ("parede", "wall"),
        "margin": ("margem", "afastamento"),
    }
    for key, aliases in named_aliases.items():
        source_text = dimension_text if key in {"length", "width", "height", "wall", "margin"} else text
        value = _extract_named_dimension(source_text, aliases)
        if value is not None:
            dimensions[key] = value
    if flange_outer_diameter is not None:
        dimensions["diameter"] = flange_outer_diameter
        dimensions["outer_diameter"] = flange_outer_diameter

    hole_count = _extract_hole_count(text)
    hole_diameter = _extract_hole_diameter(text)
    thread = _extract_thread(text)
    if hole_count:
        dimensions["hole_count"] = hole_count
    if hole_diameter is not None:
        dimensions["hole_diameter"] = hole_diameter
    elif hole_count:
        if thread:
            dimensions["hole_diameter"] = float(thread[1:])
            assumptions.append(f"Diametro dos furos nao informado; usando diametro nominal da rosca {thread}.")
        else:
            dimensions["hole_diameter"] = 6.0
            assumptions.append("Diametro dos furos nao informado; usando 6 mm.")
    if thread:
        dimensions["thread_nominal_diameter"] = float(thread[1:])

    bolt_circle_diameter, bolt_circle_radius = _extract_bolt_circle(text, part_type, hole_count)
    if bolt_circle_diameter is not None:
        dimensions["bolt_circle_diameter"] = bolt_circle_diameter
        dimensions["bolt_circle"] = bolt_circle_diameter
    if bolt_circle_radius is not None:
        dimensions["bolt_circle_radius"] = bolt_circle_radius

    if "radius" not in dimensions and "bolt_circle_radius" not in dimensions:
        radius_value = _extract_named_dimension(text, ("raio", "radius"))
        if radius_value is not None:
            dimensions["radius"] = radius_value

    if part_type in {"plate", "flange"} and "height" in dimensions and "thickness" not in dimensions:
        dimensions["thickness"] = dimensions["height"]
        dimensions.pop("height", None)

    if part_type == "cylinder" and "height" in dimensions and "length" not in dimensions:
        dimensions["length"] = dimensions.pop("height")

    slot_length, slot_width = _extract_slot_dimensions(text)
    if _contains_any(text, tuple(SLOT_TERMS.split("|"))):
        params = {"position": "center" if any(word in text for word in ("central", "centro", "dentro")) else "center"}
        if slot_length is not None:
            params["length"] = slot_length
        if slot_width is not None:
            params["width"] = slot_width
        features.append(Feature("slot", params))

    if hole_count:
        params: dict[str, object] = {
            "count": hole_count,
            "diameter": dimensions.get("hole_diameter", 6.0),
        }
        if "cantos" in text or "canto" in text:
            params["placement"] = "corners"
        elif "circulo" in text or part_type == "flange":
            params["placement"] = "bolt_circle"
        elif "cada aba" in text:
            params["placement"] = "tabs"
        else:
            params["placement"] = "default"
        if "passante" in text or part_type == "flange":
            params["through"] = True
        if thread:
            params["thread"] = thread
            params["thread_note"] = "Rosca nominal registrada; geometria de corte usa o diametro de furo informado."
        if part_type == "flange":
            if "bolt_circle_radius" in dimensions:
                params["radius"] = dimensions["bolt_circle_radius"]
            if "bolt_circle_diameter" in dimensions:
                params["diameter_primitive"] = dimensions["bolt_circle_diameter"]
            features.append(Feature("bolt_circle_holes", params))
        else:
            features.append(Feature("holes", params))

    if _contains_any(text, ("furo central", "diametro interno", "miolo")):
        features.append(Feature("center_hole", {"diameter": dimensions.get("center_hole", 25.0), "through": True}))

    if _contains_any(text, ("chanfro", "chamfer")):
        value = _extract_named_dimension(text, ("chanfro", "chamfer")) or 1.0
        features.append(Feature("chamfer", {"distance": value}))

    if _contains_any(text, ("arredond", "fillet", "raio nas bordas")):
        value = dimensions.get("radius") or _extract_named_dimension(text, ("arredondamento", "raio")) or 2.0
        features.append(Feature("fillet", {"radius": value}))

    if part_type == "box" and _contains_any(text, ("aberta", "aberto", "oca", "oco", "vazada", "vazado", "hollow")):
        features.append(Feature("hollow", {"open_top": True}))

    if _contains_any(text, ("nervura", "reforco", "rib")) or part_type == "l_bracket":
        features.append(Feature("ribs", {}))

    _apply_defaults(part_type, dimensions, assumptions, features)
    _sync_dimension_aliases(dimensions)
    if part_type == "flange":
        physical_dimension_keys = {
            "diameter",
            "outer_diameter",
            "hole_diameter",
            "bolt_circle_radius",
            "bolt_circle_diameter",
            "bolt_circle",
            "thickness",
            "center_hole",
            "center_hole_diameter",
        }
        used_values = {
            float(dimensions[key])
            for key in physical_dimension_keys
            if isinstance(dimensions.get(key), (int, float))
        }
        for value in _ambiguous_diameters_after_holes(text, used_values):
            warnings.append(
                f"Diametro de {format_mm(value)} mm apos a descricao dos furos ficou ambiguo; "
                f"nao foi usado como diametro externo. Para furo central, diga "
                f"'furo central de {format_mm(value)} mm'."
            )
    _validate_dimensions(part_type, dimensions, warnings)
    return PartSpec(
        prompt=prompt,
        part_type=part_type,
        dimensions=dimensions,
        features=tuple(features),
        material=material,
        assumptions=tuple(dict.fromkeys(assumptions)),
        warnings=tuple(dict.fromkeys(warnings)),
    )


def _apply_defaults(
    part_type: str,
    dimensions: dict[str, float],
    assumptions: list[str],
    features: list[Feature],
) -> None:
    defaults = {
        "plate": {"length": 100.0, "width": 60.0, "thickness": 5.0},
        "flange": {"diameter": 100.0, "thickness": 10.0},
        "cylinder": {"diameter": 20.0, "length": 80.0},
        "l_bracket": {"length": 80.0, "height": 60.0, "width": 30.0, "thickness": 5.0, "hole_diameter": 6.0},
        "box": {"length": 100.0, "width": 80.0, "height": 40.0, "wall": 3.0},
    }
    for key, value in defaults[part_type].items():
        if key not in dimensions:
            dimensions[key] = value
            if part_type == "flange" and key == "thickness":
                assumptions.append(f"Espessura nao informada; usando {format_mm(value)} mm.")
            else:
                assumptions.append(f"{key} padrao: {format_mm(value)} mm.")

    holes = next((feature for feature in features if feature.kind in {"holes", "bolt_circle_holes"}), None)
    if holes:
        if "margin" not in dimensions and part_type in {"plate", "l_bracket"}:
            dimensions["margin"] = 10.0
            assumptions.append("Margem dos furos nao informada; usando 10 mm.")
        if "hole_diameter" not in dimensions:
            dimensions["hole_diameter"] = float(holes.params.get("diameter", 6.0))
        dimensions.setdefault("hole_count", int(holes.params.get("count", 0)))

    slot = next((feature for feature in features if feature.kind == "slot"), None)
    if slot:
        if "length" not in slot.params:
            slot.params["length"] = min(dimensions.get("length", 100.0) * 0.35, 40.0)
            assumptions.append(f"Comprimento do rasgo nao informado; usando {format_mm(slot.params['length'])} mm.")
        if "width" not in slot.params:
            slot.params["width"] = max(dimensions.get("hole_diameter", 6.0) * 1.5, 10.0)
            assumptions.append(f"Largura do rasgo nao informada; usando {format_mm(slot.params['width'])} mm.")

    if part_type == "flange" and holes and "bolt_circle" not in dimensions and "bolt_circle_radius" not in dimensions:
        dimensions["bolt_circle"] = dimensions["diameter"] * 0.68
        assumptions.append(f"Circulo primitivo nao informado; usando {format_mm(dimensions['bolt_circle'])} mm.")


def _validate_dimensions(part_type: str, dimensions: dict[str, float], warnings: list[str]) -> None:
    positive_keys = {
        "plate": ("length", "width", "thickness"),
        "flange": ("diameter", "thickness"),
        "cylinder": ("diameter", "length"),
        "l_bracket": ("length", "height", "width", "thickness"),
        "box": ("length", "width", "height", "wall"),
    }[part_type]
    for key in positive_keys:
        if dimensions.get(key, 0) <= 0:
            warnings.append(f"Dimensao {key} invalida; verifique o prompt.")

    if part_type == "box" and dimensions["wall"] * 2 >= min(dimensions["length"], dimensions["width"]):
        warnings.append("Parede da caixa muito espessa para as dimensoes externas.")

    if part_type == "flange" and dimensions.get("center_hole", 0) >= dimensions["diameter"]:
        warnings.append("Furo central maior ou igual ao diametro externo da flange.")
