"""
Orquestador del job diario (spec sección 6). Corre después del cierre de EE.UU.:

  1. Captura la IV ATM del día        -> iv_history
  2. Recalcula IV Rank                 -> iv_rank_cache
  3. Evalúa las reglas activas         -> alerts (nuevas, con dedup 48h)
  4. Envía el correo consolidado       -> si hay alertas sin enviar

Cada paso es independiente; si uno falla se registra y se sigue con los demás
(salvo que no haya datos para continuar). Devuelve 0 si todo ok, 1 si hubo algún
fallo.
"""
from __future__ import annotations

import traceback

import daily_capture
import compute_iv_rank
import evaluate_rules
import send_email


STEPS = [
    ("Captura de IV",      daily_capture.main),
    ("Cálculo de IV Rank", compute_iv_rank.main),
    ("Motor de reglas",    evaluate_rules.main),
    ("Correo",             send_email.main),
]


def main() -> int:
    rc = 0
    for name, fn in STEPS:
        print(f"\n{'='*12} {name} {'='*12}")
        try:
            if fn() != 0:
                print(f"[{name}] terminó con código != 0")
                rc = 1
        except Exception:
            traceback.print_exc()
            print(f"[{name}] EXCEPCIÓN — se continúa con el siguiente paso")
            rc = 1
    print(f"\nFin del job diario (rc={rc}).")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
