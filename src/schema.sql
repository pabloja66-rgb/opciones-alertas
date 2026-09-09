-- ============================================================
--  Opciones Alertas — esquema base
--  Ejecutar UNA sola vez en Supabase:
--    Dashboard -> SQL Editor -> New query -> pegar todo -> Run
-- ============================================================

-- ----- Tickers vigilados (spec secciones 2 y 2.1) -----------
create table if not exists watched_tickers (
    symbol     text primary key,
    active     boolean     not null default true,
    added_at   timestamptz not null default now()
);

-- ----- Historial de IV ATM por ticker y fecha (spec sec. 5) -
--  Un registro = una "foto" de la volatilidad implícita del
--  contrato más cercano a ATM (~30 días a vencimiento) en esa
--  fecha. Es la materia prima del IV Rank (paso 2).
create table if not exists iv_history (
    ticker           text        not null,
    date             date        not null,
    atm_iv           numeric,               -- IV ATM = promedio(call_iv, put_iv)
    underlying_price numeric,               -- cierre de la acción esa fecha
    expiration_used  date,                  -- vencimiento del contrato usado
    strike_used      numeric,               -- strike usado (el más cercano al precio)
    dte_used         integer,               -- días a vencimiento en esa fecha
    call_iv          numeric,
    put_iv           numeric,
    source           text        not null default 'alpha_vantage_historical',
    fetched_at       timestamptz not null default now(),
    primary key (ticker, date)
);

create index if not exists iv_history_ticker_date_idx
    on iv_history (ticker, date desc);

-- ----- Caché de IV Rank (spec sec. 5) — se llena en el paso 2
create table if not exists iv_rank_cache (
    ticker          text        primary key,
    current_iv_rank numeric,
    window_days_used integer,               -- cuántos días de historial hay
    last_computed   timestamptz not null default now()
);
-- columnas extra para el dashboard y el texto de "por qué se disparó"
alter table iv_rank_cache add column if not exists current_iv     numeric;  -- IV ATM más reciente
alter table iv_rank_cache add column if not exists iv_percentile  numeric;  -- % de días con IV <= actual
alter table iv_rank_cache add column if not exists iv_min_window  numeric;
alter table iv_rank_cache add column if not exists iv_max_window  numeric;
alter table iv_rank_cache add column if not exists n_observations integer;  -- nº de fotos en la ventana
alter table iv_rank_cache add column if not exists as_of_date     date;     -- fecha de la IV actual usada

-- ----- Reglas de alerta (spec sec. 3 y 5) -------------------
--  Umbrales editables sin tocar código. Una fila = una regla.
create table if not exists alert_rules (
    rule_id      text        primary key,
    type         text        not null,     -- 'sell_put' | 'buy_call'
    applies_to   text        not null default 'open',  -- 'open' | 'open_position' (sec. 10)
    iv_rank_min  numeric,                  -- null = sin límite inferior
    iv_rank_max  numeric,                  -- null = sin límite superior
    delta_min    numeric,
    delta_max    numeric,
    dte_min      integer,
    dte_max      integer,                  -- null = sin límite superior
    active       boolean     not null default true,
    notes        text
);

-- ----- Alertas generadas (spec sec. 5) ---------------------
create table if not exists alerts (
    alert_id          text        primary key,  -- ticker:rule:YYYY-MM-DD
    ticker            text        not null,
    rule_type         text        not null,
    rule_id           text,
    strike            numeric,
    expiration        date,
    dte               integer,
    delta             numeric,
    theta             numeric,
    iv                numeric,               -- IV del contrato
    iv_rank           numeric,               -- IV Rank del ticker al disparar
    premium_estimate  numeric,               -- por acción (x100 = por contrato)
    underlying_price  numeric,
    reasons           jsonb       not null default '[]',
    created_at        timestamptz not null default now(),
    emailed           boolean     not null default false
);
create index if not exists alerts_ticker_created_idx on alerts (ticker, created_at desc);
-- métricas de "qué tan cara está la prima" (ver src/metrics.py)
alter table alerts add column if not exists intrinsic                     numeric;
alter table alerts add column if not exists extrinsic                     numeric;
alter table alerts add column if not exists breakeven_price              numeric;
alter table alerts add column if not exists breakeven_move_pct           numeric;  -- call: % que debe subir; put: % que puede caer (negativo)
alter table alerts add column if not exists breakeven_move_annualized_pct numeric;
alter table alerts add column if not exists premium_pct_of_underlying    numeric;
alter table alerts add column if not exists effective_leverage           numeric;  -- solo calls
alter table alerts add column if not exists return_on_capital_pct        numeric;  -- solo puts (prima / garantía)
alter table alerts add column if not exists return_annualized_pct        numeric;  -- solo puts
alter table alerts add column if not exists quality                      text;     -- 'green' | 'yellow' | 'red'
alter table alerts add column if not exists quality_detail               jsonb default '[]';  -- color por criterio

-- ----- Semilla de reglas de apertura (spec sec. 3) --------
insert into alert_rules (rule_id, type, iv_rank_min, iv_rank_max, delta_min, delta_max, dte_min, dte_max, notes) values
    ('sell_put_income', 'sell_put', 55, null, 0.20, 0.30, 25, 45,
     'Vender PUT para generar prima. Strike <= precio actual (OTM).'),
    ('buy_call_leaps',  'buy_call', null, 40,  0.70, 0.85, 180, 550,
     'Comprar CALL LEAPS (6-18 meses) como sustituto de accion. Prefiere ~12 meses.')
on conflict (rule_id) do nothing;

-- tope de 18 meses para LEAPS en instalaciones previas donde quedó abierto
update alert_rules set dte_max = 550
 where rule_id = 'buy_call_leaps' and dte_max is null;

-- ----- Semilla de tickers vigilados ------------------------
insert into watched_tickers (symbol) values
    ('HOOD'), ('PLTR'), ('TSLA'), ('DUOL'), ('AMD'), ('HIMS'),
    ('IBIT'), ('NU'), ('AMZN'), ('QQQ'), ('IBRX')
on conflict (symbol) do nothing;
