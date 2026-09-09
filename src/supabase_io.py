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


def fetch_iv_history(select: str = "ticker,date,atm_iv") -> list[dict]:
    """Trae todo iv_history (paginado), ordenado por ticker y fecha."""
    out: list[dict] = []
    step = 1000
    offset = 0
    while True:
        resp = _session.get(
            f"{SUPABASE_URL}/rest/v1/iv_history",
            headers=_headers(),
            params={"select": select, "order": "ticker,date",
                    "limit": step, "offset": offset},
            timeout=60,
        )
        resp.raise_for_status()
        chunk = resp.json()
        out.extend(chunk)
        if len(chunk) < step:
            return out
        offset += step


def get_active_rules() -> list[dict]:
    resp = _session.get(
        f"{SUPABASE_URL}/rest/v1/alert_rules",
        headers=_headers(),
        params={"select": "*", "active": "eq.true", "applies_to": "eq.open"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def get_iv_rank_map() -> dict[str, dict]:
    resp = _session.get(
        f"{SUPABASE_URL}/rest/v1/iv_rank_cache",
        headers=_headers(),
        params={"select": "*"},
        timeout=30,
    )
    resp.raise_for_status()
    return {r["ticker"]: r for r in resp.json()}


def recent_alerts(since_iso: str) -> list[dict]:
    resp = _session.get(
        f"{SUPABASE_URL}/rest/v1/alerts",
        headers=_headers(),
        params={"select": "*", "created_at": f"gte.{since_iso}", "order": "created_at.desc"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def upsert_alerts(rows: list[dict]) -> int:
    if not rows:
        return 0
    resp = _session.post(
        f"{SUPABASE_URL}/rest/v1/alerts",
        headers=_headers({"Prefer": "resolution=merge-duplicates,return=minimal"}),
        json=rows,
        timeout=60,
    )
    if resp.status_code >= 300:
        raise RuntimeError(f"Supabase {resp.status_code}: {resp.text[:400]}")
    return len(rows)


def upsert_iv_rank(rows: list[dict]) -> int:
    resp = _session.post(
        f"{SUPABASE_URL}/rest/v1/iv_rank_cache",
        headers=_headers({"Prefer": "resolution=merge-duplicates,return=minimal"}),
        json=rows,
        timeout=60,
    )
    if resp.status_code >= 300:
        raise RuntimeError(f"Supabase {resp.status_code}: {resp.text[:400]}")
    return len(rows)


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
