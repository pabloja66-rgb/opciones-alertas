"""
PASO 10.3 — Seguimiento de posiciones abiertas y alertas de salida.

Para cada fila de `positions` con status='open':
  1. Busca el contrato exacto (ticker+strike+expiration+tipo) en la cadena de la
     última sesión.
  2. Calcula el valor actual y el % de ganancia/pérdida vs. la prima de entrada.
  3. Evalúa las reglas de salida (alert_rules con applies_to='open_position').
  4. Guarda el estado en la fila (current_*, pnl_pct, exit_signal, exit_reasons).
  5. Si dispara y la posición es real, crea una alerta rule_type='close_position'
     para el correo diario (sección "Posiciones para cerrar"), con dedup de 48 h.

Las posiciones simuladas se valoran igual (para el dashboard) pero NO generan correo.
"""
from __future__ import annotations

import datetime as dt
import sys

import config
from alpha_vantage import AlphaVantageError, historical_options
from evaluate_rules import _f, parse_chain
from supabase_io import (
    get_active_rules,
    get_iv_rank_map,
    get_open_positions,
    recent_alerts,
    update_position,
    upsert_alerts,
)

DEDUP_HOURS = 48
WANT_TYPE = {"buy_call_leaps": "call", "sell_put": "put"}


def _premium(c: dict) -> float | None:
    for k in ("mark", "last"):
        v = _f(c.get(k))
        if v and v > 0:
            return v
    b, a = _f(c.get("bid")), _f(c.get("ask"))
    if b and a and b > 0 and a > 0:
        return round((b + a) / 2, 4)
    return None


def find_contract(raw: list[dict], pos: dict):
    want = WANT_TYPE.get(pos["type"])
    exp = str(pos["expiration"])
    strike = _f(pos["strike"])
    for c in raw:
        if c.get("type") == want and str(c.get("expiration")) == exp and _f(c.get("strike")) == strike:
            return c
    return None


def evaluate_exit(pos: dict, rule: dict, *, current_prem: float, entry_prem: float,
                  cur_delta: float | None, cur_ivr: float | None, dte_now: int) -> list[str]:
    reasons: list[str] = []
    if pos["type"] == "buy_call_leaps":
        gain = (current_prem - entry_prem) / entry_prem * 100
        if rule.get("gain_take_profit_pct") is not None and gain >= float(rule["gain_take_profit_pct"]):
            reasons.append(f"Ganancia {gain:.0f}% sobre la prima pagada (${entry_prem:.2f} → ${current_prem:.2f})")
        if rule.get("delta_take_profit") is not None and cur_delta is not None and abs(cur_delta) >= float(rule["delta_take_profit"]):
            reasons.append(f"Delta actual {abs(cur_delta):.2f} ≥ {float(rule['delta_take_profit']):.2f} — ya casi no hay ventaja de apalancamiento, considerar rolar")
        ent_ivr = _f(pos.get("entry_iv_rank"))
        if rule.get("iv_rank_jump_pts") is not None and ent_ivr is not None and cur_ivr is not None \
           and cur_ivr - ent_ivr >= float(rule["iv_rank_jump_pts"]):
            reasons.append(f"IV Rank subió de {ent_ivr:.0f}% a {cur_ivr:.0f}% — el extrínseco se infló, buen momento de vender")
    else:  # sell_put
        pct_left = current_prem / entry_prem * 100
        if rule.get("put_value_pct_of_premium") is not None and pct_left <= float(rule["put_value_pct_of_premium"]):
            reasons.append(f"El put vale ${current_prem:.2f} = {pct_left:.0f}% de la prima cobrada (${entry_prem:.2f}) — ya capturaste {100-pct_left:.0f}%")
        if rule.get("gamma_risk_dte") is not None and dte_now < int(rule["gamma_risk_dte"]) \
           and cur_delta is not None and abs(cur_delta) < float(rule.get("gamma_risk_max_delta") or 0.1):
            reasons.append(f"Quedan {dte_now} días y sigue muy OTM (delta {abs(cur_delta):.2f}) — riesgo de gamma, cerrar ya")
    return reasons


def run() -> list[dict]:
    positions = get_open_positions()
    if not positions:
        print("Sin posiciones abiertas.")
        return []
    rules = {r["type"]: r for r in get_active_rules("open_position")}
    ivr_map = get_iv_rank_map()
    since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=DEDUP_HOURS)).isoformat()
    prev_close = [a for a in recent_alerts(since) if a["rule_type"] == "close_position"]
    already = {a.get("ticker") + str(a.get("strike")) + str(a.get("expiration")) for a in prev_close}

    chains: dict[str, list[dict]] = {}
    new_alerts: list[dict] = []
    today = dt.date.today()

    for p in positions:
        tk = p["ticker"]
        if tk not in chains:
            try:
                chains[tk] = historical_options(tk)
            except AlphaVantageError as e:
                print(f"  {tk:6} ! {e}"); chains[tk] = []
        raw = chains[tk]
        c = find_contract(raw, p) if raw else None
        if not c:
            print(f"  {p['ticker']:6} {p['type']:14} contrato no encontrado (K {p['strike']} {p['expiration']})")
            continue
        cur = _premium(c)
        if cur is None:
            print(f"  {p['ticker']:6} sin precio para el contrato"); continue
        entry = float(p["entry_premium"])
        cur_delta = _f(c.get("delta"))
        cur_ivr = _f((ivr_map.get(tk) or {}).get("current_iv_rank"))
        dte_now = (dt.date.fromisoformat(str(p["expiration"])) - today).days
        long = p["type"] == "buy_call_leaps"
        pnl = (cur - entry) / entry * 100 if long else (entry - cur) / entry * 100

        rule = rules.get(p["type"], {})
        reasons = evaluate_exit(p, rule, current_prem=cur, entry_prem=entry,
                                cur_delta=cur_delta, cur_ivr=cur_ivr, dte_now=dte_now) if rule else []
        signal = bool(reasons)

        update_position(p["position_id"], {
            "current_premium": round(cur, 4),
            "current_delta": round(cur_delta, 4) if cur_delta is not None else None,
            "current_iv_rank": round(cur_ivr, 1) if cur_ivr is not None else None,
            "pnl_pct": round(pnl, 1),
            "exit_signal": signal,
            "exit_reasons": reasons,
            "last_priced": dt.datetime.now(dt.timezone.utc).isoformat(),
        })
        tag = "CERRAR" if signal else "mantener"
        print(f"  {p['ticker']:6} {p['type']:14} P&L {pnl:+.0f}%  -> {tag}  {'; '.join(reasons)}")

        if signal and p["mode"] == "real":
            key = tk + str(_f(p["strike"])) + str(p["expiration"])
            if key in already:
                print(f"         (ya alertado en {DEDUP_HOURS}h)")
                continue
            sess = c.get("date") or today.isoformat()
            new_alerts.append({
                "alert_id": f"{p['position_id']}:close:{sess}",
                "ticker": tk,
                "rule_type": "close_position",
                "rule_id": rule.get("rule_id"),
                "strike": _f(p["strike"]),
                "expiration": str(p["expiration"]),
                "dte": dte_now,
                "delta": round(cur_delta, 4) if cur_delta is not None else None,
                "iv": _f(c.get("implied_volatility")),
                "iv_rank": round(cur_ivr, 1) if cur_ivr is not None else None,
                "premium_estimate": round(cur, 4),
                "underlying_price": None,
                "reasons": [f"Posición abierta el {p['entry_date']} · {p['contracts']} contrato(s) · P&L {pnl:+.0f}%"] + reasons,
                "emailed": False,
            })

    if new_alerts:
        upsert_alerts(new_alerts)
        print(f"-> {len(new_alerts)} alerta(s) de cierre para el correo")
    return new_alerts


def main() -> int:
    if not config.ALPHAVANTAGE_API_KEY:
        print("ERROR: falta ALPHAVANTAGE_API_KEY", file=sys.stderr)
        return 1
    print("Seguimiento de posiciones abiertas...")
    run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
