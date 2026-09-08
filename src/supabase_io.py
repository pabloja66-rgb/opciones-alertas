"""Lectura/escritura contra Supabase vía PostgREST (sin dependencias extra)."""
import requests

from config import SUPABASE_SECRET_KEY, SUPABASE_URL

_session = requests.Session()


def _headers(extra: dict | None = None) -> dict:
    h = {
        "apikey": SUPABASE_SECRET_KEY,
        "Authorization": f"Bearer {SUPABASE_SECRET_KEY}",
        "Content-Type": "application/json",
    }
    if extra:
        h.update(extra)
    return h


def get_active_tickers() -> list[str]:
    """Lee watched_tickers activos. Lanza excepción si la tabla no existe."""
    resp = _session.get(
        f"{SUPABASE_URL}/rest/v1/watched_tickers",
        headers=_headers(),
        params={"select": "symbol", "active": "eq.true", "order": "symbol"},
        timeout=30,
    )
    resp.raise_for_status()
    return [row["symbol"] for row in resp.json()]


def upsert_iv_history(rows: list[dict], *, batch: int = 500) -> int:
    """Inserta/actualiza en iv_history por (ticker, date). Devuelve filas enviadas."""
    total = 0
    for i in range(0, len(rows), batch):
        chunk = rows[i : i + batch]
        resp = _session.post(
            f"{SUPABASE_URL}/rest/v1/iv_history",
            headers=_headers({"Prefer": "resolution=merge-duplicates,return=minimal"}),
            json=chunk,
            timeout=60,
        )
        if resp.status_code >= 300:
            raise RuntimeError(f"Supabase {resp.status_code}: {resp.text[:400]}")
        total += len(chunk)
    return total
