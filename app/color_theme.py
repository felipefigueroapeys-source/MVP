COLOR_5_SCALE = {
    1: {"name": "Rojo", "emoji": "🔴", "hex": "#D32F2F", "label": "Descartar"},
    2: {"name": "Naranjo", "emoji": "🟠", "hex": "#F57C00", "label": "Débil"},
    3: {"name": "Amarillo", "emoji": "🟡", "hex": "#FBC02D", "label": "Vigilancia"},
    4: {"name": "Verde claro", "emoji": "🟢", "hex": "#7CB342", "label": "Candidato"},
    5: {"name": "Verde oscuro", "emoji": "🟩", "hex": "#1B5E20", "label": "Prioridad"},
}

COLOR_3_SCALE = {
    1: {"name": "Rojo", "emoji": "🔴", "hex": "#D32F2F", "label": "No apto"},
    2: {"name": "Amarillo", "emoji": "🟡", "hex": "#FBC02D", "label": "Vigilar"},
    3: {"name": "Verde", "emoji": "🟢", "hex": "#2E7D32", "label": "Apto"},
}


def color_5_from_score(score: int) -> dict:
    if score >= 18:
        return COLOR_5_SCALE[5]
    if score >= 14:
        return COLOR_5_SCALE[4]
    if score >= 10:
        return COLOR_5_SCALE[3]
    if score >= 7:
        return COLOR_5_SCALE[2]
    return COLOR_5_SCALE[1]


def color_5_from_sector_score(score: int) -> dict:
    if score >= 10:
        return COLOR_5_SCALE[5]
    if score >= 7:
        return COLOR_5_SCALE[4]
    if score >= 4:
        return COLOR_5_SCALE[3]
    if score >= 1:
        return COLOR_5_SCALE[2]
    return COLOR_5_SCALE[1]


def color_3_from_bool(value: bool) -> dict:
    return COLOR_3_SCALE[3] if value else COLOR_3_SCALE[1]
