"""Configuración central del sistema de alertas de opciones."""
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# La consola de Windows suele ser cp1252 y revienta con acentos/símbolos.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

# --- Credenciales (vienen de .env en local, de secrets en GitHub Actions) ---
ALPHAVANTAGE_API_KEY = os.environ.get("ALPHAVANTAGE_API_KEY", "").strip()
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
SUPABASE_SECRET_KEY = os.environ.get("SUPABASE_SECRET_KEY", "").strip()

# --- Parámetros del backfill (spec secciones 4 y 9) ---
BACKFILL_WEEKS = 52          # ~12 meses, 1 "foto" por semana
BACKFILL_WEEKDAY = 2         # 0=lunes, 1=martes, 2=miércoles ...
DTE_TARGET = 30             # días a vencimiento objetivo del contrato ATM
DTE_MIN = 25
DTE_MAX = 45
DTE_HARD_MIN = 15          # si no hay nada en [25,45], se acepta hasta acá
DTE_HARD_MAX = 60          # (y hasta acá), registrando el dte real usado

# --- Rate limit de Alpha Vantage (plan 75 req/min = US$49.99) ---
AV_RATE_LIMIT_PER_MIN = 75
REQUEST_SLEEP = 60.0 / AV_RATE_LIMIT_PER_MIN + 0.15  # margen de seguridad

# --- Lista de respaldo si no se puede leer watched_tickers de la base ---
FALLBACK_TICKERS = [
    "HOOD", "PLTR", "TSLA", "DUOL", "AMD", "HIMS",
    "IBIT", "NU", "AMZN", "QQQ", "IBRX",
]

DATA_DIR = ROOT / "data"
