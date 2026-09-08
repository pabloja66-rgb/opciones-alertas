"""Cliente mínimo de Alpha Vantage con manejo de rate limit y reintentos."""
import time

import requests

from config import ALPHAVANTAGE_API_KEY, REQUEST_SLEEP

BASE_URL = "https://www.alphavantage.co/query"

_session = requests.Session()


class AlphaVantageError(RuntimeError):
    pass


def _get(params: dict, *, max_retries: int = 4) -> dict:
    """Llamada GET a Alpha Vantage devolviendo JSON. Reintenta ante throttling."""
    params = {**params, "apikey": ALPHAVANTAGE_API_KEY, "datatype": "json"}
    backoff = 15.0
    for intento in range(1, max_retries + 1):
        resp = _session.get(BASE_URL, params=params, timeout=60)
        resp.raise_for_status()
        try:
            payload = resp.json()
        except ValueError:
            raise AlphaVantageError(f"Respuesta no-JSON: {resp.text[:200]}")

        # Mensajes de throttling / límite de Alpha Vantage
        blob = str(payload).lower()
        throttled = (
            "rate_limit" in blob
            or "higher api call volume" in blob
            or "please subscribe" in blob and "premium endpoint" in blob and "data" not in payload
        )
        if isinstance(payload, dict) and ("Note" in payload or "Information" in payload):
            throttled = True

        if throttled and intento < max_retries:
            time.sleep(backoff)
            backoff *= 2
            continue
        if throttled:
            raise AlphaVantageError(f"Rate limit persistente: {str(payload)[:300]}")
        return payload
    raise AlphaVantageError("agotados los reintentos")


def daily_closes(symbol: str) -> dict[str, float]:
    """{fecha 'YYYY-MM-DD': cierre} con 20+ años de historia (endpoint gratuito)."""
    payload = _get({
        "function": "TIME_SERIES_DAILY",
        "symbol": symbol,
        "outputsize": "full",
    })
    series = payload.get("Time Series (Daily)")
    if not series:
        raise AlphaVantageError(f"{symbol}: sin serie diaria ({str(payload)[:200]})")
    time.sleep(REQUEST_SLEEP)
    return {d: float(v["4. close"]) for d, v in series.items()}


def historical_options(symbol: str, date: str) -> list[dict]:
    """Cadena de opciones completa de `symbol` en `date` (YYYY-MM-DD). Premium."""
    payload = _get({
        "function": "HISTORICAL_OPTIONS",
        "symbol": symbol,
        "date": date,
    })
    time.sleep(REQUEST_SLEEP)
    data = payload.get("data")
    if data is None:
        # días sin sesión, o antes de que existieran las opciones del ticker
        return []
    return data
