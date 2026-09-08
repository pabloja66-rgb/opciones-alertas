"""Verifica que las credenciales y la base estén listas antes del backfill."""
import sys

import requests

import config
from supabase_io import get_active_tickers


def check_env() -> bool:
    ok = True
    if config.ALPHAVANTAGE_API_KEY:
        print("  [ok] ALPHAVANTAGE_API_KEY presente")
    else:
        print("  [--] ALPHAVANTAGE_API_KEY vacía (necesaria para el backfill)")
        ok = False
    if config.SUPABASE_URL and config.SUPABASE_SECRET_KEY:
        print(f"  [ok] Supabase configurado: {config.SUPABASE_URL}")
    else:
        print("  [XX] faltan SUPABASE_URL / SUPABASE_SECRET_KEY")
        ok = False
    return ok


def check_alpha_vantage() -> bool:
    if not config.ALPHAVANTAGE_API_KEY:
        print("  [--] omitido (sin API key todavía)")
        return False
    r = requests.get(
        "https://www.alphavantage.co/query",
        params={
            "function": "HISTORICAL_OPTIONS",
            "symbol": "AMD",
            "date": "2025-06-18",
            "apikey": config.ALPHAVANTAGE_API_KEY,
            "datatype": "json",
        },
        timeout=60,
    )
    data = r.json()
    if isinstance(data, dict) and data.get("data"):
        print(f"  [ok] HISTORICAL_OPTIONS responde ({len(data['data'])} contratos para AMD)")
        return True
    print(f"  [XX] HISTORICAL_OPTIONS no disponible: {str(data)[:200]}")
    return False


def check_supabase_tables() -> bool:
    try:
        tk = get_active_tickers()
    except requests.HTTPError as e:
        if "404" in str(e):
            print("  [XX] la tabla watched_tickers no existe -> corre src/schema.sql en el SQL Editor")
        else:
            print(f"  [XX] error consultando Supabase: {e}")
        return False
    print(f"  [ok] watched_tickers: {len(tk)} activos -> {', '.join(tk)}")
    return True


def main() -> int:
    print("1) Variables de entorno");            e = check_env()
    print("2) Alpha Vantage (HISTORICAL_OPTIONS)"); a = check_alpha_vantage()
    print("3) Tablas en Supabase");              s = check_supabase_tables()
    print()
    if e and a and s:
        print("TODO LISTO -> puedes correr:  python src/backfill_iv.py")
        return 0
    print("Faltan pasos (ver arriba).")
    return 1


if __name__ == "__main__":
    sys.exit(main())
