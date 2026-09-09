"""
PASO 4 — Correo consolidado de alertas (spec sección 7).

Lee las alertas con emailed=false, arma UN solo correo HTML con tabla resumen +
motivos + semáforo, lo envía por Gmail SMTP y marca emailed=true.

Uso:
  python src/send_email.py
  python src/send_email.py --dry-run     # escribe el HTML en data/, no envía
"""
from __future__ import annotations

import argparse
import datetime as dt
import smtplib
import ssl
import sys
from email.mime.text import MIMEText

import requests

import config
from supabase_io import SUPABASE_URL, _headers

DOT = {"green": "🟢", "yellow": "🟡", "red": "🔴"}
ACTION = {"sell_put": "Vender PUT", "buy_call": "Comprar CALL LEAPS"}
SECTION_TITLE = {"sell_put": "Vender PUT (generar prima)",
                 "buy_call": "Comprar CALL LEAPS (sustituto de acción)"}


def fetch_unemailed() -> list[dict]:
    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/alerts",
        headers=_headers(),
        params={"select": "*", "emailed": "eq.false", "order": "rule_type,quality,ticker"},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def mark_emailed(ids: list[str]) -> None:
    if not ids:
        return
    id_list = ",".join(f'"{i}"' for i in ids)
    r = requests.patch(
        f"{SUPABASE_URL}/rest/v1/alerts",
        headers=_headers({"Prefer": "return=minimal"}),
        params={"alert_id": f"in.({id_list})"},
        json={"emailed": True},
        timeout=30,
    )
    r.raise_for_status()


# --------------------------------------------------------------------------- #
def _num(x, default=None):
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def row_html(a: dict) -> str:
    q = a.get("quality") or "yellow"
    delta = abs(_num(a["delta"], 0))
    strike = _num(a["strike"], 0)
    ivr = _num(a["iv_rank"], 0)
    if a["rule_type"] == "buy_call":
        extra = (f"sube {_num(a['breakeven_move_pct'],0):.1f}% a break-even · "
                 f"apalanc. {_num(a['effective_leverage'],0):.1f}x")
    else:
        extra = (f"{_num(a['return_annualized_pct'],0):.0f}%/año · "
                 f"colchón {abs(_num(a['breakeven_move_pct'],0)):.1f}%")
    reasons = "".join(f"<li>{r}</li>" for r in (a.get("reasons") or []))
    return f"""
    <tr>
      <td style="padding:8px 6px;font-size:18px;text-align:center">{DOT.get(q,'')}</td>
      <td style="padding:8px 6px;font-weight:bold">{a['ticker']}</td>
      <td style="padding:8px 6px">{ACTION.get(a['rule_type'], a['rule_type'])}</td>
      <td style="padding:8px 6px">${strike:,.0f}</td>
      <td style="padding:8px 6px">{a['expiration']}</td>
      <td style="padding:8px 6px">{delta:.2f}</td>
      <td style="padding:8px 6px">{ivr:.0f}%</td>
      <td style="padding:8px 6px;color:#555">{extra}</td>
    </tr>
    <tr>
      <td></td>
      <td colspan="7" style="padding:0 6px 14px 6px;color:#666;font-size:13px">
        <ul style="margin:4px 0 0 0;padding-left:18px">{reasons}</ul>
      </td>
    </tr>"""


def section_html(rule_type: str, rows: list[dict]) -> str:
    body = "".join(row_html(a) for a in rows)
    return f"""
    <h3 style="margin:22px 0 6px 0;font-family:system-ui,Arial">{SECTION_TITLE.get(rule_type, rule_type)}</h3>
    <table style="border-collapse:collapse;width:100%;font-family:system-ui,Arial;font-size:14px">
      <thead>
        <tr style="text-align:left;border-bottom:2px solid #ddd">
          <th style="padding:6px"></th><th style="padding:6px">Ticker</th>
          <th style="padding:6px">Acción</th><th style="padding:6px">Strike</th>
          <th style="padding:6px">Venc.</th><th style="padding:6px">Delta</th>
          <th style="padding:6px">IV Rank</th><th style="padding:6px">Detalle</th>
        </tr>
      </thead>
      <tbody>{body}</tbody>
    </table>"""


def build_email(alerts: list[dict]) -> tuple[str, str]:
    n = len(alerts)
    subject = f"📈 Oportunidades de opciones — {n} {'señal' if n == 1 else 'señales'} hoy"
    by_type: dict[str, list[dict]] = {}
    for a in alerts:
        by_type.setdefault(a["rule_type"], []).append(a)

    counts = " · ".join(
        f"{DOT[c]} {sum(1 for a in alerts if a.get('quality') == c)}"
        for c in ("green", "yellow", "red")
    )
    sections = "".join(section_html(rt, by_type[rt]) for rt in ("buy_call", "sell_put") if rt in by_type)
    link = (f'<p style="font-family:system-ui,Arial;font-size:14px">'
            f'<a href="{config.DASHBOARD_URL}">Ver detalle en el dashboard →</a></p>'
            if config.DASHBOARD_URL else "")

    html = f"""<div style="max-width:820px;margin:0 auto">
    <p style="font-family:system-ui,Arial;font-size:14px;color:#333">
      {dt.date.today():%d-%b-%Y} · {n} alertas ({counts})
    </p>
    {sections}
    {link}
    <p style="font-family:system-ui,Arial;font-size:12px;color:#999;margin-top:24px;border-top:1px solid #eee;padding-top:10px">
      🟢/🟡/🔴 = qué tan favorable está la mecánica (prima, volatilidad, apalancamiento),
      no una orden de compra. La convicción sobre la empresa y el tamaño de la posición
      los decides tú. Generado automáticamente desde iv_history + alert_rules.
    </p>
    </div>"""
    return subject, html


# --------------------------------------------------------------------------- #
def send(subject: str, html: str, recipients: list[str]) -> None:
    msg = MIMEText(html, "html", "utf-8")
    msg["Subject"] = subject
    msg["From"] = config.GMAIL_ADDRESS
    msg["To"] = ", ".join(recipients)
    ctx = ssl.create_default_context()
    with smtplib.SMTP("smtp.gmail.com", 587, timeout=30) as s:
        s.starttls(context=ctx)
        s.login(config.GMAIL_ADDRESS, config.GMAIL_APP_PASSWORD)
        s.sendmail(config.GMAIL_ADDRESS, recipients, msg.as_string())


def main() -> int:
    ap = argparse.ArgumentParser(description="Envía el correo de alertas")
    ap.add_argument("--dry-run", action="store_true", help="escribe el HTML, no envía")
    ap.add_argument("--test", action="store_true",
                    help="envía solo a GMAIL_ADDRESS y NO marca las alertas como enviadas")
    args = ap.parse_args()

    alerts = fetch_unemailed()
    if not alerts:
        print("No hay alertas pendientes de enviar.")
        return 0

    recipients = [config.GMAIL_ADDRESS] if args.test else config.EMAIL_RECIPIENTS
    subject, html = build_email(alerts)
    if args.test:
        subject = "[PRUEBA] " + subject
    print(f"Asunto: {subject}")
    print(f"Para:   {', '.join(recipients)}")
    print(f"Alertas: {len(alerts)}")

    if args.dry_run:
        config.DATA_DIR.mkdir(exist_ok=True)
        out = config.DATA_DIR / f"email_{dt.datetime.now():%Y%m%d_%H%M%S}.html"
        out.write_text(f"<!doctype html><meta charset=utf-8><title>{subject}</title>{html}",
                       encoding="utf-8")
        print(f"\n[dry-run] HTML escrito en {out}")
        return 0

    if not config.GMAIL_APP_PASSWORD:
        print("ERROR: falta GMAIL_APP_PASSWORD en .env", file=sys.stderr)
        return 1
    send(subject, html, recipients)
    if args.test:
        print(f"\n[PRUEBA] Enviado a {config.GMAIL_ADDRESS}. Alertas NO marcadas.")
        return 0
    mark_emailed([a["alert_id"] for a in alerts])
    print(f"\nEnviado. {len(alerts)} alertas marcadas como emailed=true.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
