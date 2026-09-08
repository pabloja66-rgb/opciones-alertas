# opciones-alertas

Sistema de alertas de opciones (vender puts / comprar calls LEAPS) sobre el
portafolio de Pablo. Ver la especificación completa en
`spec-alertas-opciones.md` (carpeta de Drive `Inversiones/Opciones`).

## Estado

| Paso (spec §9) | Estado |
|---|---|
| 1. Backfill retroactivo de IV (12 meses) | **en curso** — este repo |
| 2. Cálculo de IV Rank | pendiente |
| 3. Motor de reglas | pendiente |
| 4. Envío de correo (Gmail) | pendiente |
| 5. Tarjetas del dashboard | pendiente |

## Arquitectura (decidida con Pablo)

- **Datos históricos de opciones:** Alpha Vantage `HISTORICAL_OPTIONS`
  (plan 75 req/min, US$49.99 — se paga **un solo mes** para el backfill).
- **Datos del día a día (a futuro):** API de Interactive Brokers (sin costo mensual).
- **Base de datos:** Supabase (Postgres gestionado, plan gratuito).
- **Automatización:** GitHub Actions (nada corre en el PC de Pablo).

## Puesta en marcha del Paso 1

1. **Credenciales** — copia `.env.example` a `.env` y rellena:
   - `ALPHAVANTAGE_API_KEY` (tras activar el plan)
   - `SUPABASE_URL`, `SUPABASE_SECRET_KEY` (ya rellenos)

2. **Crear las tablas** — en Supabase: *SQL Editor → New query →* pega el
   contenido de [`src/schema.sql`](src/schema.sql) *→ Run*. Esto crea
   `watched_tickers`, `iv_history`, `iv_rank_cache` y siembra los 11 tickers.

3. **Dependencias**
   ```
   python -m pip install -r requirements.txt
   ```

4. **Verificar** que todo está conectado
   ```
   python src/check_setup.py
   ```

5. **Correr el backfill**
   ```
   python src/backfill_iv.py --tickers AMD MSFT SPY   # prueba con 3
   python src/backfill_iv.py                          # los 11 watched_tickers
   ```
   Deja una copia local en `data/` y sube todo a `iv_history` en Supabase.
   Es re-ejecutable: hace upsert por `(ticker, date)`, no duplica.

## Tickers vigilados

HOOD, PLTR, TSLA, DUOL, AMD, HIMS, IBIT, NU, AMZN, QQQ, IBRX
(editable en la tabla `watched_tickers`).
