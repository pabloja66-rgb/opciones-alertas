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

-- ----- Semilla de tickers vigilados ------------------------
insert into watched_tickers (symbol) values
    ('HOOD'), ('PLTR'), ('TSLA'), ('DUOL'), ('AMD'), ('HIMS'),
    ('IBIT'), ('NU'), ('AMZN'), ('QQQ'), ('IBRX')
on conflict (symbol) do nothing;
