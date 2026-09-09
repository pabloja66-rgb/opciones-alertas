"""
Captura diaria de IV (spec sección 6.1c). Tras el cierre de EE.UU., para cada
ticker vigilado toma la cadena de la última sesión, extrae la IV del contrato
ATM (~30 DTE) y la agrega a `iv_history`. Idempotente: upsert por (ticker, date).

Es la versión "un día" del backfill; después de que corrió el backfill de 12
meses, esto mantiene el historial al día con 1 llamada por ticker.
"""
from __future__ import annotations

import sys

import config
from alpha_vantage import AlphaVantageError, global_quote, historical_options
from backfill_iv import pick_atm
from supabase_io import get_active_tickers, upsert_iv_history


def run(tickers: list[str] | None = None) -> list[dict]:
    tickers = tickers or get_active_tickers()
    rows: list[dict] = []
    for t in tickers:
        try:
            chain = historical_options(t)          # sin fecha = sesión anterior
            spot = global_quote(t).get("price")
        except AlphaVantageError as e:
            print(f"  {t:6} ! {e}")
            continue
        if not chain or spot is None:
            print(f"  {t:6} sin cadena/precio")
            continue
        session = chain[0].get("date")
        rec = pick_atm(chain, session, spot)
        if rec is None:
            print(f"  {t:6} sin contrato ATM usable")
            continue
        rec["ticker"] = t
        rec["source"] = "alpha_vantage_daily"
        rows.append(rec)
        print(f"  {t:6} {session}  IV ATM {rec['atm_iv']:.3f}  (strike {rec['strike_used']}, dte {rec['dte_used']})")

    if rows:
        upsert_iv_history(rows)
        print(f"-> {len(rows)} filas upserteadas en iv_history")
    return rows


def main() -> int:
    if not config.ALPHAVANTAGE_API_KEY:
        print("ERROR: falta ALPHAVANTAGE_API_KEY", file=sys.stderr)
        return 1
    print("Captura diaria de IV...")
    run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
