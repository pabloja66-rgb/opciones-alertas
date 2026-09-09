"""
Recalcula la columna `quality` (semáforo) de las alertas existentes a partir de
sus métricas ya guardadas. Útil tras cambiar umbrales en scoring.py o al añadir
la columna. No borra nada: solo hace UPDATE.

Uso:  python src/backfill_quality.py
"""
from __future__ import annotations

import requests

from scoring import score
from supabase_io import SUPABASE_URL, _headers  # type: ignore

_s = requests.Session()


def main() -> int:
    r = _s.get(
        f"{SUPABASE_URL}/rest/v1/alerts",
        headers=_headers(),
        params={"select": "alert_id,rule_type,iv_rank,breakeven_move_pct,"
                          "effective_leverage,return_annualized_pct"},
        timeout=30,
    )
    r.raise_for_status()
    rows = r.json()
    n = 0
    for a in rows:
        m = {
            "iv_rank": float(a["iv_rank"]) if a.get("iv_rank") is not None else None,
            "breakeven_move_pct": float(a["breakeven_move_pct"]) if a.get("breakeven_move_pct") is not None else None,
            "effective_leverage": float(a["effective_leverage"]) if a.get("effective_leverage") is not None else None,
            "return_annualized_pct": float(a["return_annualized_pct"]) if a.get("return_annualized_pct") is not None else None,
        }
        quality, detail = score(a["rule_type"], m)
        up = _s.patch(
            f"{SUPABASE_URL}/rest/v1/alerts",
            headers=_headers({"Prefer": "return=minimal"}),
            params={"alert_id": f"eq.{a['alert_id']}"},
            json={"quality": quality, "quality_detail": detail},
            timeout=30,
        )
        up.raise_for_status()
        n += 1
        print(f"  {a['alert_id']:28} -> {quality}")
    print(f"\n{n} alertas recalificadas.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
