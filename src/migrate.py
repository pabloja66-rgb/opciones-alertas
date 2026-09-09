"""Aplica src/schema.sql a la base de Supabase (conexión directa a Postgres)."""
import os
import sys
from pathlib import Path

import pg8000.native
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def connect() -> pg8000.native.Connection:
    return pg8000.native.Connection(
        host=os.environ["SUPABASE_DB_HOST"],
        port=int(os.environ.get("SUPABASE_DB_PORT", 5432)),
        user=os.environ["SUPABASE_DB_USER"],
        password=os.environ["SUPABASE_DB_PASSWORD"],
        database=os.environ.get("SUPABASE_DB_NAME", "postgres"),
        ssl_context=True,
    )


def main() -> int:
    sql = (ROOT / "src" / "schema.sql").read_text(encoding="utf-8")
    con = connect()
    try:
        con.run(sql)
        print("schema.sql aplicado.")
        rows = con.run(
            "select table_name from information_schema.tables "
            "where table_schema = 'public' order by table_name"
        )
        print("Tablas en public:", ", ".join(r[0] for r in rows))
        tk = con.run("select symbol from watched_tickers order by symbol")
        print(f"watched_tickers ({len(tk)}):", ", ".join(r[0] for r in tk))
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
