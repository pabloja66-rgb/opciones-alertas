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


def historical_options(symbol: str, date: str | None = None) -> list[dict]:
    """Cadena de opciones completa de `symbol`.

    Con `date` (YYYY-MM-DD): esa sesión histórica.
    Sin `date`: la sesión de mercado anterior (lo que usa el job diario tras el
    cierre para tener el cierre del día). Endpoint premium.
    """
    params = {"function": "HISTORICAL_OPTIONS", "symbol": symbol}
    if date:
        params["date"] = date
    payload = _get(params)
    time.sleep(REQUEST_SLEEP)
    data = payload.get("data")
    if data is None:
        # días sin sesión, o antes de que existieran las opciones del ticker
        return []
    return data


def global_quote(symbol: str) -> dict:
    """Precio y volumen más recientes del subyacente (endpoint gratuito)."""
    payload = _get({"function": "GLOBAL_QUOTE", "symbol": symbol})
    time.sleep(REQUEST_SLEEP)
    q = payload.get("Global Quote") or payload.get("Global Quote - DATA DELAYED BY 15 MINUTES") or {}
    return {
        "price": float(q["05. price"]) if q.get("05. price") else None,
        "latest_day": q.get("07. latest trading day"),
    }
