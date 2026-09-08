"""
PASO 1 — Backfill retroactivo del historial de IV (spec sección 9.1).

Para cada ticker vigilado:
  1. Baja 20+ años de cierres diarios (1 llamada, endpoint gratuito).
  2. Genera ~52 fechas "objetivo" (un miércoles por semana, 12 meses atrás).
     Si un miércoles fue feriado, retrocede al día hábil anterior.
  3. Para cada fecha pide la cadena histórica de opciones (HISTORICAL_OPTIONS).
  4. Elige el vencimiento con DTE más cercano a 30 (dentro de 25-45), y dentro
     de ese vencimiento el strike más cercano al precio de cierre => contrato ATM.
  5. Guarda atm_iv = promedio(IV del call, IV del put) de ese strike.
  6. Sube todo a Supabase (iv_history) y deja una copia local en data/.

Uso:
  python src/backfill_iv.py                 # todos los watched_tickers
  python src/backfill_iv.py --tickers AMD MSFT SPY
  python src/backfill_iv.py --dry-run       # no escribe en Supabase, solo data/
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import sys
from statistics import mean

import config
from alpha_vantage import AlphaVantageError, daily_closes, historical_options
from supabase_io import get_active_tickers, upsert_iv_history


# --------------------------------------------------------------------------- #
#  Fechas objetivo
# --------------------------------------------------------------------------- #
def target_dates(closes: dict[str, float]) -> list[str]:
    """~52 fechas hábiles, una por semana (miércoles o el hábil anterior)."""
    today = dt.date.today()
    # último `BACKFILL_WEEKDAY` (miércoles) no futuro
    offset = (today.weekday() - config.BACKFILL_WEEKDAY) % 7
    anchor = today - dt.timedelta(days=offset or 7)  # el miércoles pasado, no hoy

    fechas: list[str] = []
    for w in range(config.BACKFILL_WEEKS):
        day = anchor - dt.timedelta(weeks=w)
        # retroceder hasta encontrar un día con cierre (feriados/fines de semana)
        for _ in range(6):
            key = day.isoformat()
            if key in closes:
                if key not in fechas:
                    fechas.append(key)
                break
            day -= dt.timedelta(days=1)
    return sorted(fechas)


# --------------------------------------------------------------------------- #
#  Selección del contrato ATM
# --------------------------------------------------------------------------- #
def _num(x) -> float | None:
    try:
        v = float(x)
        return v if v > 0 else None
    except (TypeError, ValueError):
        return None


def pick_atm(chain: list[dict], as_of: str, spot: float) -> dict | None:
    """Devuelve el registro iv_history para una fecha, o None si no hay datos usables."""
    as_of_d = dt.date.fromisoformat(as_of)

    # agrupar por vencimiento con su DTE
    by_exp: dict[str, int] = {}
    for row in chain:
        exp = row.get("expiration")
        if not exp:
            continue
        try:
            dte = (dt.date.fromisoformat(exp) - as_of_d).days
        except ValueError:
            continue
        if dte > 0:
            by_exp[exp] = dte

    if not by_exp:
        return None

    # vencimiento con DTE más cercano a 30, priorizando la ventana 25-45
    en_ventana = {e: d for e, d in by_exp.items() if config.DTE_MIN <= d <= config.DTE_MAX}
    candidatos = en_ventana or {
        e: d for e, d in by_exp.items()
        if config.DTE_HARD_MIN <= d <= config.DTE_HARD_MAX
    }
    if not candidatos:
        return None
    exp = min(candidatos, key=lambda e: abs(candidatos[e] - config.DTE_TARGET))
    dte_used = by_exp[exp]

    # dentro del vencimiento, strike más cercano al spot
    strikes: dict[float, dict[str, float | None]] = {}
    for row in chain:
        if row.get("expiration") != exp:
            continue
        k = _num(row.get("strike"))
        if k is None:
            continue
        iv = _num(row.get("implied_volatility"))
        slot = strikes.setdefault(k, {"call": None, "put": None})
        slot[row.get("type", "")] = iv

    if not strikes:
        return None
    strike = min(strikes, key=lambda k: abs(k - spot))
    ivs = [v for v in (strikes[strike]["call"], strikes[strike]["put"]) if v is not None]
    if not ivs:
        # el strike ATM exacto no traía IV: probar el siguiente más cercano
        for k in sorted(strikes, key=lambda k: abs(k - spot)):
            ivs = [v for v in (strikes[k]["call"], strikes[k]["put"]) if v is not None]
            if ivs:
                strike = k
                break
    if not ivs:
        return None

    return {
        "ticker": None,  # lo rellena el caller
        "date": as_of,
        "atm_iv": round(mean(ivs), 6),
        "underlying_price": round(spot, 4),
        "expiration_used": exp,
        "strike_used": strike,
        "dte_used": dte_used,
        "call_iv": strikes[strike]["call"],
        "put_iv": strikes[strike]["put"],
        "source": "alpha_vantage_historical",
    }


# --------------------------------------------------------------------------- #
#  Backfill de un ticker
# --------------------------------------------------------------------------- #
def backfill_ticker(symbol: str) -> list[dict]:
    print(f"\n=== {symbol} ===", flush=True)
    try:
        closes = daily_closes(symbol)
    except AlphaVantageError as e:
        print(f"  ! sin serie de precios: {e}")
        return []

    fechas = target_dates(closes)
    print(f"  {len(fechas)} fechas objetivo ({fechas[0]} -> {fechas[-1]})", flush=True)

    rows: list[dict] = []
    sin_datos = 0
    for i, fecha in enumerate(fechas, 1):
        try:
            chain = historical_options(symbol, fecha)
        except AlphaVantageError as e:
            print(f"  ! {fecha}: {e}")
            continue
        rec = pick_atm(chain, fecha, closes[fecha]) if chain else None
        if rec is None:
            sin_datos += 1
            continue
        rec["ticker"] = symbol
        rows.append(rec)
        if i % 10 == 0:
            print(f"  {i}/{len(fechas)}  ...ultimo IV={rec['atm_iv']:.3f} @ {fecha}", flush=True)

    print(f"  -> {len(rows)} fotos capturadas, {sin_datos} fechas sin datos usables")
    return rows


# --------------------------------------------------------------------------- #
#  Salidas locales
# --------------------------------------------------------------------------- #
def dump_local(rows: list[dict]) -> None:
    config.DATA_DIR.mkdir(exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    j = config.DATA_DIR / f"backfill_iv_{stamp}.json"
    c = config.DATA_DIR / f"backfill_iv_{stamp}.csv"
    j.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    if rows:
        with c.open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
    print(f"\nCopia local: {j.name} / {c.name}")


def summary(rows: list[dict]) -> None:
    print("\n---------------- RESUMEN ----------------")
    by_t: dict[str, list[dict]] = {}
    for r in rows:
        by_t.setdefault(r["ticker"], []).append(r)
    for t in sorted(by_t):
        rs = sorted(by_t[t], key=lambda r: r["date"])
        ivs = [r["atm_iv"] for r in rs]
        print(
            f"  {t:6}  {len(rs):3} fotos  "
            f"{rs[0]['date']} -> {rs[-1]['date']}  "
            f"IV min/med/max = {min(ivs):.2f}/{mean(ivs):.2f}/{max(ivs):.2f}"
        )
    print(f"  TOTAL: {len(rows)} registros para iv_history")
    print("----------------------------------------")


# --------------------------------------------------------------------------- #
def main() -> int:
    ap = argparse.ArgumentParser(description="Backfill retroactivo de IV")
    ap.add_argument("--tickers", nargs="+", help="lista explícita (default: watched_tickers)")
    ap.add_argument("--dry-run", action="store_true", help="no escribe en Supabase")
    args = ap.parse_args()

    if not config.ALPHAVANTAGE_API_KEY:
        print("ERROR: falta ALPHAVANTAGE_API_KEY en .env", file=sys.stderr)
        return 1
    if not (config.SUPABASE_URL and config.SUPABASE_SECRET_KEY):
        print("ERROR: faltan SUPABASE_URL / SUPABASE_SECRET_KEY en .env", file=sys.stderr)
        return 1

    if args.tickers:
        tickers = [t.upper() for t in args.tickers]
    else:
        try:
            tickers = get_active_tickers()
        except Exception as e:
            print(f"No pude leer watched_tickers ({e}); uso la lista de respaldo.")
            tickers = config.FALLBACK_TICKERS
    print(f"Tickers: {', '.join(tickers)}")

    all_rows: list[dict] = []
    for t in tickers:
        all_rows.extend(backfill_ticker(t))

    if not all_rows:
        print("\nNo se capturó ningún dato. Revisa la API key o los tickers.")
        return 1

    dump_local(all_rows)
    summary(all_rows)

    if args.dry_run:
        print("\n[dry-run] no se escribió en Supabase.")
        return 0

    print("\nSubiendo a Supabase (iv_history)...", flush=True)
    n = upsert_iv_history(all_rows)
    print(f"OK: {n} registros upserteados en iv_history.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
