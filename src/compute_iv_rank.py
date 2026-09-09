"""
PASO 2 — Cálculo de IV Rank (spec sección 9.2).

Sobre el historial que ya está en `iv_history`, para cada ticker calcula:

  IV Rank      = (IV_actual - IV_min) / (IV_max - IV_min) * 100
                 sobre la ventana de los últimos 365 días de historial.
                 Responde: "¿qué tan cara está la volatilidad hoy vs. su
                 propio rango del último año?" (0 = mínimo del año, 100 = máximo).

  IV Percentil = % de fotos de la ventana con IV <= IV_actual.
                 Menos sensible a un único pico extremo que el IV Rank.

Escribe el resultado en `iv_rank_cache` (una fila por ticker).
No consume API externa: solo lee y escribe en Supabase.

Uso:
  python src/compute_iv_rank.py
  python src/compute_iv_rank.py --dry-run
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys

from supabase_io import fetch_iv_history, upsert_iv_rank

WINDOW_DAYS = 365


def _clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))


def compute_rows(history: list[dict]) -> list[dict]:
    by_ticker: dict[str, list[tuple[dt.date, float]]] = {}
    for r in history:
        iv = r.get("atm_iv")
        if iv is None:
            continue
        by_ticker.setdefault(r["ticker"], []).append(
            (dt.date.fromisoformat(r["date"]), float(iv))
        )

    out: list[dict] = []
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    for ticker, serie in by_ticker.items():
        serie.sort()
        as_of, current_iv = serie[-1]
        cutoff = as_of - dt.timedelta(days=WINDOW_DAYS)
        window = [(d, v) for d, v in serie if d >= cutoff]
        ivs = [v for _, v in window]

        lo, hi = min(ivs), max(ivs)
        iv_rank = 0.0 if hi == lo else (current_iv - lo) / (hi - lo) * 100.0
        pctile = 100.0 * sum(1 for v in ivs if v <= current_iv) / len(ivs)
        span_days = (window[-1][0] - window[0][0]).days

        out.append({
            "ticker": ticker,
            "current_iv": round(current_iv, 6),
            "current_iv_rank": round(_clamp(iv_rank), 1),
            "iv_percentile": round(pctile, 1),
            "iv_min_window": round(lo, 6),
            "iv_max_window": round(hi, 6),
            "n_observations": len(window),
            "window_days_used": span_days,
            "as_of_date": as_of.isoformat(),
            "last_computed": now,
        })
    return sorted(out, key=lambda r: r["ticker"])


def main() -> int:
    ap = argparse.ArgumentParser(description="Calcula IV Rank sobre iv_history")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    history = fetch_iv_history()
    if not history:
        print("iv_history está vacío. Corre primero src/backfill_iv.py")
        return 1

    rows = compute_rows(history)

    print(f"{'ticker':7} {'IV act':>7} {'IVrank':>7} {'IVpctl':>7} "
          f"{'min':>6} {'max':>6}  fotos  dias  fecha")
    for r in rows:
        print(f"{r['ticker']:7} {r['current_iv']:7.3f} {r['current_iv_rank']:7.1f} "
              f"{r['iv_percentile']:7.1f} {r['iv_min_window']:6.2f} {r['iv_max_window']:6.2f}"
              f"  {r['n_observations']:4}  {r['window_days_used']:4}  {r['as_of_date']}")

    if args.dry_run:
        print("\n[dry-run] no se escribió en iv_rank_cache.")
        return 0

    n = upsert_iv_rank(rows)
    print(f"\nOK: {n} filas en iv_rank_cache.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
