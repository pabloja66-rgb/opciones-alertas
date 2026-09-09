"""
Métricas de "qué tan cara está la prima" para una opción.

CALL (sustituto de acción):
  intrinseco   = max(0, precio - strike)          -> parte que ya "tienes"
  extrinseco   = prima - intrinseco               -> lo que pagas por el tiempo
  break-even   = strike + prima                    -> precio al que empatas al vencer
  subida %     = (break-even - precio) / precio    -> cuánto debe subir la acción
  subida %/año = subida % * 365 / DTE              -> para comparar plazos distintos
  prima/precio = prima / precio                    -> % del valor de la acción que pones
  apalancam.   = precio * |delta| / prima          -> cada $1 se mueve como $X de acción

PUT vendido (cash-secured):
  break-even   = strike - prima                    -> bajo esto empiezas a perder
  colchón %    = (precio - break-even) / precio    -> cuánto puede caer antes de perder
  rend. gar.   = prima / strike                    -> % sobre el capital de garantía
  rend. %/año  = rend. gar. * 365 / DTE
"""
from __future__ import annotations


def call_metrics(spot: float, strike: float, premium: float, dte: int, delta: float) -> dict:
    intrinsic = max(0.0, spot - strike)
    extrinsic = premium - intrinsic
    be_price = strike + premium
    be_move = (be_price - spot) / spot * 100.0
    return {
        "intrinsic": round(intrinsic, 4),
        "extrinsic": round(extrinsic, 4),
        "breakeven_price": round(be_price, 4),
        "breakeven_move_pct": round(be_move, 2),                      # + = debe subir
        "breakeven_move_annualized_pct": round(be_move * 365.0 / dte, 2) if dte else None,
        "premium_pct_of_underlying": round(premium / spot * 100.0, 2),
        "effective_leverage": round(spot * abs(delta) / premium, 2) if premium else None,
        "return_annualized_pct": None,
    }


def put_metrics(spot: float, strike: float, premium: float, dte: int, delta: float) -> dict:
    intrinsic = max(0.0, strike - spot)
    extrinsic = premium - intrinsic
    be_price = strike - premium
    cushion = (spot - be_price) / spot * 100.0
    roc = premium / strike * 100.0
    return {
        "intrinsic": round(intrinsic, 4),
        "extrinsic": round(extrinsic, 4),
        "breakeven_price": round(be_price, 4),
        "breakeven_move_pct": round(-cushion, 2),                     # - = puede caer
        "breakeven_move_annualized_pct": None,
        "premium_pct_of_underlying": round(premium / spot * 100.0, 2),
        "effective_leverage": None,
        "return_annualized_pct": round(roc * 365.0 / dte, 2) if dte else None,
        "return_on_capital_pct": round(roc, 2),
    }
