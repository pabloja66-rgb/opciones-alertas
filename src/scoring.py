"""
Semáforo de calidad de una alerta (🟢 / 🟡 / 🔴).

Traduce las métricas a un color por criterio y un color global (el peor de los
criterios — "la cadena es tan fuerte como su eslabón más débil").

Los umbrales viven aquí, en un solo lugar, para poder ajustarlos fácil.
"""
from __future__ import annotations

ORDER = {"green": 0, "yellow": 1, "red": 2}

# criterio -> (verde si, amarillo si) ; el resto es rojo.
# cada test recibe el valor y devuelve bool.
BUY_CALL = {
    "iv_rank":        (lambda v: v <= 20, lambda v: v <= 40),
    "breakeven_move": (lambda v: v < 10,  lambda v: v <= 20),
    "leverage":       (lambda v: v >= 2.5, lambda v: v >= 1.8),
}
SELL_PUT = {
    "iv_rank":        (lambda v: v >= 65, lambda v: v >= 55),
    "return_annual":  (lambda v: v >= 20, lambda v: v >= 12),
    "cushion":        (lambda v: v >= 12, lambda v: v >= 7),
}

LABELS = {
    "iv_rank": "IV Rank",
    "breakeven_move": "Subida a break-even",
    "leverage": "Apalancamiento",
    "return_annual": "Rendimiento anualizado",
    "cushion": "Colchón a break-even",
}


def _color(value: float | None, green_test, yellow_test) -> str:
    if value is None:
        return "yellow"
    if green_test(value):
        return "green"
    if yellow_test(value):
        return "yellow"
    return "red"


def score(rule_type: str, m: dict) -> tuple[str, list[dict]]:
    if rule_type == "sell_put":
        values = {
            "iv_rank": m.get("iv_rank"),
            "return_annual": m.get("return_annualized_pct"),
            "cushion": abs(m["breakeven_move_pct"]) if m.get("breakeven_move_pct") is not None else None,
        }
        tests = SELL_PUT
    else:
        values = {
            "iv_rank": m.get("iv_rank"),
            "breakeven_move": m.get("breakeven_move_pct"),
            "leverage": m.get("effective_leverage"),
        }
        tests = BUY_CALL

    detail: list[dict] = []
    points = 0          # verde=2, amarillo=1, rojo=0  (máx 6)
    n_red = 0
    for key, (gt, yt) in tests.items():
        c = _color(values[key], gt, yt)
        detail.append({"criterio": LABELS[key], "valor": values[key], "color": c})
        points += {"green": 2, "yellow": 1, "red": 0}[c]
        n_red += c == "red"

    # Cualquier criterio en rojo topa el global en amarillo; con pocos puntos, rojo.
    if n_red:
        overall = "red" if points <= 3 else "yellow"
    else:
        overall = "green" if points >= 5 else "yellow"
    return overall, detail
