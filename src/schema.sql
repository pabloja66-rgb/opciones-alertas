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

-- ----- Portafolios (para agrupar/filtrar posiciones) ------
create table if not exists portfolios (
    portfolio_id text        primary key,   -- slug corto
    name         text        not null,
    created_at   timestamptz not null default now()
);
insert into portfolios (portfolio_id, name) values ('principal', 'Principal')
on conflict (portfolio_id) do nothing;

-- ----- Posiciones abiertas / simuladas (spec sec. 10) -----
create table if not exists positions (
    position_id    text        primary key,
    mode           text        not null default 'real',   -- 'real' | 'sim'
    portfolio_id   text,                                    -- null para simulaciones
    ticker         text        not null,
    type           text        not null,     -- 'sell_put' | 'buy_call_leaps'
    strike         numeric     not null,
    expiration     date        not null,
    entry_premium  numeric     not null,     -- lo que pagó (call) o cobró (put), por acción
    entry_date     date        not null default current_date,
    entry_iv_rank  numeric,                  -- IV Rank del ticker al abrir (para regla de salida)
    contracts      integer     not null default 1,
    status         text        not null default 'open',    -- 'open' | 'closed'
    exit_premium   numeric,
    exit_date      date,
    notes          text,
    -- estado calculado por el job diario:
    current_premium numeric,
    current_delta   numeric,
    current_iv_rank numeric,
    pnl_pct         numeric,                 -- % ganancia/pérdida sobre entry_premium
    exit_signal     boolean     not null default false,
    exit_reasons    jsonb       not null default '[]',
    last_priced     timestamptz,
    created_at     timestamptz not null default now()
);
create index if not exists positions_status_idx on positions (status, mode);
alter table positions add column if not exists portfolio_id    text;
alter table positions add column if not exists entry_iv_rank   numeric;
alter table positions add column if not exists current_premium numeric;
alter table positions add column if not exists current_delta   numeric;
alter table positions add column if not exists current_iv_rank numeric;
alter table positions add column if not exists pnl_pct         numeric;
alter table positions add column if not exists exit_signal     boolean not null default false;
alter table positions add column if not exists exit_reasons    jsonb not null default '[]';
alter table positions add column if not exists last_priced     timestamptz;

-- ----- Row Level Security: lectura pública para el dashboard -
-- El job diario usa la service key y NO pasa por estas políticas.
do $$
declare t text;
begin
  foreach t in array array['watched_tickers','iv_history','iv_rank_cache','alert_rules','alerts','positions','portfolios']
  loop
    execute format('alter table %I enable row level security', t);
    execute format('drop policy if exists anon_read on %I', t);
    execute format('create policy anon_read on %I for select to anon using (true)', t);
  end loop;
  -- el dashboard puede gestionar la watchlist, las posiciones y los portafolios
  foreach t in array array['watched_tickers','positions','portfolios']
  loop
    execute format('drop policy if exists anon_write on %I', t);
    execute format('create policy anon_write on %I for all to anon using (true) with check (true)', t);
  end loop;
end $$;

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

-- ----- Reglas de SALIDA (spec sec. 10.2) -------------------
alter table alert_rules add column if not exists gain_take_profit_pct     numeric;  -- call: ganancia % que dispara
alter table alert_rules add column if not exists delta_take_profit        numeric;  -- call: delta actual que dispara
alter table alert_rules add column if not exists iv_rank_jump_pts         numeric;  -- call: subida de IV Rank vs. entrada (puntos)
alter table alert_rules add column if not exists put_value_pct_of_premium numeric;  -- put: valor actual <= X% de la prima cobrada
alter table alert_rules add column if not exists gamma_risk_dte           integer;  -- put: DTE por debajo del cual
alter table alert_rules add column if not exists gamma_risk_max_delta     numeric;  -- put: y |delta| por debajo de (muy OTM)

insert into alert_rules (rule_id, type, applies_to, active, notes,
                         gain_take_profit_pct, delta_take_profit, iv_rank_jump_pts,
                         put_value_pct_of_premium, gamma_risk_dte, gamma_risk_max_delta) values
    ('exit_call_leaps', 'buy_call_leaps', 'open_position', true,
     'Tomar utilidad en un CALL LEAPS comprado si se cumple CUALQUIERA.',
     100, 0.90, 25, null, null, null),
    ('exit_sell_put', 'sell_put', 'open_position', true,
     'Recomprar y cerrar un PUT vendido si se cumple CUALQUIERA.',
     null, null, null, 30, 7, 0.10)
on conflict (rule_id) do nothing;

-- ----- Semilla de tickers vigilados ------------------------
insert into watched_tickers (symbol) values
    ('HOOD'), ('PLTR'), ('TSLA'), ('DUOL'), ('AMD'), ('HIMS'),
    ('IBIT'), ('NU'), ('AMZN'), ('QQQ'), ('IBRX')
on conflict (symbol) do nothing;
