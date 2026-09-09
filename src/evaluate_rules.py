"""
PASO 3 — Motor de reglas (spec sección 9.3, reglas de la sección 3).

Para cada ticker vigilado:
  1. Lee su IV Rank de `iv_rank_cache`.
  2. Baja la cadena de opciones de la última sesión (Alpha Vantage) y el precio.
  3. Evalúa cada regla activa de `alert_rules` (applies_to='open'):
       - filtro por IV Rank del ticker
       - filtro por tipo de contrato, |delta|, DTE y strike
  4. Del conjunto que cumple, elige UN contrato por (ticker, regla) — el de
     delta más cercano al centro del rango — y arma la alerta con los motivos
     concretos en texto.
  5. Evita duplicados: no repite ticker+regla si ya hubo alerta en 48 h sin
     cambio material (>10% IV Rank o strike distinto).
  6. Guarda las alertas nuevas en `alerts` con emailed=false (el correo es el paso 4).

Uso:
  python src/evaluate_rules.py
  python src/evaluate_rules.py --dry-run
  python src/evaluate_rules.py --tickers AMD NU
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys

from alpha_vantage import AlphaVantageError, global_quote, historical_options
from metrics import call_metrics, put_metrics
from supabase_io import (
    get_active_rules,
    get_active_tickers,
    get_iv_rank_map,
    recent_alerts,
    upsert_alerts,
)
import config

DEDUP_HOURS = 48
IV_RANK_MATERIAL_PCT = 10.0  # cambio relativo que rompe el dedup
TARGET_LEAPS_DTE = 365       # vencimiento preferido para la regla de calls (~12 meses)


# --------------------------------------------------------------------------- #
def _f(x) -> float | None:
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _premium(c: dict) -> float | None:
    for key in ("mark", "last"):
        v = _f(c.get(key))
        if v and v > 0:
            return v
    bid, ask = _f(c.get("bid")), _f(c.get("ask"))
    if bid and ask and bid > 0 and ask > 0:
        return round((bid + ask) / 2, 4)
    return None


def parse_chain(raw: list[dict]) -> tuple[list[dict], dt.date | None]:
    """Normaliza contratos y calcula DTE. Devuelve (contratos, fecha_sesion)."""
    out: list[dict] = []
    sesion: dt.date | None = None
    for c in raw:
        try:
            exp = dt.date.fromisoformat(c["expiration"])
            asof = dt.date.fromisoformat(c["date"])
        except (KeyError, ValueError):
            continue
        sesion = sesion or asof
        delta = _f(c.get("delta"))
        strike = _f(c.get("strike"))
        if delta is None or strike is None:
            continue
        out.append({
            "type": c.get("type"),
            "strike": strike,
            "expiration": exp,
            "dte": (exp - asof).days,
            "delta": delta,
            "theta": _f(c.get("theta")),
            "iv": _f(c.get("implied_volatility")),
            "premium": _premium(c),
        })
    return out, sesion


# --------------------------------------------------------------------------- #
def iv_rank_ok(rule: dict, ivr: float | None) -> bool:
    if ivr is None:
        return False
    if rule.get("iv_rank_min") is not None and ivr < float(rule["iv_rank_min"]):
        return False
    if rule.get("iv_rank_max") is not None and ivr > float(rule["iv_rank_max"]):
        return False
    return True


def contract_matches(rule: dict, c: dict, spot: float) -> bool:
    want_type = "put" if rule["type"] == "sell_put" else "call"
    if c["type"] != want_type:
        return False
    ad = abs(c["delta"])
    if rule.get("delta_min") is not None and ad < float(rule["delta_min"]):
        return False
    if rule.get("delta_max") is not None and ad > float(rule["delta_max"]):
        return False
    if rule.get("dte_min") is not None and c["dte"] < int(rule["dte_min"]):
        return False
    if rule.get("dte_max") is not None and c["dte"] > int(rule["dte_max"]):
        return False
    if rule["type"] == "sell_put" and c["strike"] > spot:
        return False  # el put vendido es OTM: strike <= precio
    if c["premium"] is None:
        return False
    return True


def pick_best(rule: dict, matches: list[dict]) -> dict:
    center = (float(rule["delta_min"]) + float(rule["delta_max"])) / 2
    pool = matches
    if rule["type"] == "buy_call":
        # primero el vencimiento más cercano a ~12 meses, luego el delta al centro
        by_exp: dict[dt.date, list[dict]] = {}
        for c in matches:
            by_exp.setdefault(c["expiration"], []).append(c)
        target_exp = min(by_exp, key=lambda e: abs(by_exp[e][0]["dte"] - TARGET_LEAPS_DTE))
        pool = by_exp[target_exp]
    return min(pool, key=lambda c: abs(abs(c["delta"]) - center))


def reasons_for(rule: dict, c: dict, ivr: float, spot: float, m: dict) -> list[str]:
    ad = abs(c["delta"])
    prem_contract = c["premium"] * 100
    if rule["type"] == "sell_put":
        return [
            f"IV Rank {ivr:.0f}% — volatilidad cara vs. su último año, prima inflada",
            f"Delta {ad:.2f} → ≈{ad*100:.0f}% de probabilidad de asignación",
            f"{c['dte']} días a vencimiento ({c['expiration']:%d-%b})",
            f"Prima ${c['premium']:.2f}/acción → ${prem_contract:.0f} por contrato",
            f"Rinde {m['return_on_capital_pct']:.1f}% sobre la garantía (${c['strike']*100:.0f}) "
            f"en {c['dte']} días ≈ {m['return_annualized_pct']:.0f}%/año",
            f"Break-even ${m['breakeven_price']:.2f}: la acción puede caer "
            f"{abs(m['breakeven_move_pct']):.1f}% antes de que pierdas",
        ]
    meses = c["dte"] / 30
    return [
        f"IV Rank {ivr:.0f}% — volatilidad barata, buen momento de entrada (regla ≤ {rule['iv_rank_max']:.0f}%)",
        f"Delta {ad:.2f} → se mueve casi 1:1 con la acción, poco castigo por theta",
        f"{c['dte']} días a vencimiento (~{meses:.0f} meses)",
        f"Prima ${c['premium']:.2f}/acción = ${m['intrinsic']:.2f} intrínseco + "
        f"${m['extrinsic']:.2f} de tiempo ({m['premium_pct_of_underlying']:.0f}% del precio)",
        f"Break-even ${m['breakeven_price']:.2f} → la acción debe subir "
        f"{m['breakeven_move_pct']:.1f}% para {c['expiration']:%b-%y} ({m['breakeven_move_annualized_pct']:.1f}%/año)",
        f"Apalancamiento efectivo {m['effective_leverage']:.1f}x — cada $1 se mueve como "
        f"${m['effective_leverage']:.1f} de acción",
    ]


# --------------------------------------------------------------------------- #
def is_duplicate(prev: list[dict], ticker: str, rule_type: str, ivr: float, strike: float) -> bool:
    for a in prev:
        if a["ticker"] != ticker or a["rule_type"] != rule_type:
            continue
        old_ivr = _f(a.get("iv_rank"))
        same_strike = _f(a.get("strike")) == strike
        moved = old_ivr is None or old_ivr == 0 or abs(ivr - old_ivr) / old_ivr * 100 > IV_RANK_MATERIAL_PCT
        if same_strike and not moved:
            return True
    return False


def evaluate(tickers: list[str]) -> list[dict]:
    rules = get_active_rules()
    if not rules:
        print("No hay reglas activas en alert_rules.")
        return []
    ivr_map = get_iv_rank_map()
    since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=DEDUP_HOURS)).isoformat()
    prev = recent_alerts(since)

    alerts: list[dict] = []
    for ticker in tickers:
        ivr_row = ivr_map.get(ticker)
        ivr = _f(ivr_row["current_iv_rank"]) if ivr_row else None
        applicable = [r for r in rules if iv_rank_ok(r, ivr)]
        if not applicable:
            print(f"  {ticker:6} IV Rank {ivr}  — ninguna regla aplica")
            continue
        try:
            raw = historical_options(ticker)
            quote = global_quote(ticker)
        except AlphaVantageError as e:
            print(f"  {ticker:6} ! {e}")
            continue
        spot = quote.get("price")
        contracts, sesion = parse_chain(raw)
        if not contracts or spot is None:
            print(f"  {ticker:6} sin cadena/precio usable")
            continue

        for rule in applicable:
            matches = [c for c in contracts if contract_matches(rule, c, spot)]
            if not matches:
                print(f"  {ticker:6} {rule['rule_id']:16} IV Rank {ivr:.0f}%  — 0 contratos cumplen")
                continue
            best = pick_best(rule, matches)
            if is_duplicate(prev, ticker, rule["type"], ivr, best["strike"]):
                print(f"  {ticker:6} {rule['rule_id']:16} — ya alertado en {DEDUP_HOURS}h (sin cambio material)")
                continue
            calc = (put_metrics if rule["type"] == "sell_put" else call_metrics)(
                spot, best["strike"], best["premium"], best["dte"], best["delta"]
            )
            alert = {
                "alert_id": f"{ticker}:{rule['type']}:{sesion.isoformat()}",
                "ticker": ticker,
                "rule_type": rule["type"],
                "rule_id": rule["rule_id"],
                "strike": best["strike"],
                "expiration": best["expiration"].isoformat(),
                "dte": best["dte"],
                "delta": round(best["delta"], 4),
                "theta": best["theta"],
                "iv": best["iv"],
                "iv_rank": round(ivr, 1),
                "premium_estimate": best["premium"],
                "underlying_price": round(spot, 4),
                "intrinsic": calc["intrinsic"],
                "extrinsic": calc["extrinsic"],
                "breakeven_price": calc["breakeven_price"],
                "breakeven_move_pct": calc["breakeven_move_pct"],
                "breakeven_move_annualized_pct": calc["breakeven_move_annualized_pct"],
                "premium_pct_of_underlying": calc["premium_pct_of_underlying"],
                "effective_leverage": calc["effective_leverage"],
                "return_on_capital_pct": calc.get("return_on_capital_pct"),
                "return_annualized_pct": calc["return_annualized_pct"],
                "reasons": reasons_for(rule, best, ivr, spot, calc),
                "emailed": False,
            }
            alerts.append(alert)
            print(f"  {ticker:6} {rule['rule_id']:16} [ALERTA] strike ${best['strike']:.0f} "
                  f"delta {abs(best['delta']):.2f} dte {best['dte']} prima ${best['premium']:.2f}")
    return alerts


# --------------------------------------------------------------------------- #
def main() -> int:
    ap = argparse.ArgumentParser(description="Evalúa alert_rules y genera alerts")
    ap.add_argument("--tickers", nargs="+")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not config.ALPHAVANTAGE_API_KEY:
        print("ERROR: falta ALPHAVANTAGE_API_KEY", file=sys.stderr)
        return 1

    tickers = [t.upper() for t in args.tickers] if args.tickers else get_active_tickers()
    print(f"Evaluando {len(tickers)} tickers contra las reglas activas...\n")

    alerts = evaluate(tickers)
    print(f"\n{len(alerts)} alertas nuevas.")

    if not alerts:
        return 0
    if args.dry_run:
        import json
        print(json.dumps(alerts, indent=2, ensure_ascii=False))
        print("\n[dry-run] no se escribió en alerts.")
        return 0

    n = upsert_alerts(alerts)
    print(f"OK: {n} alertas guardadas en alerts (emailed=false).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
