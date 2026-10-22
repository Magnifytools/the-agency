-- 002 — Comprobaciones manuales, progreso visible y calendario de barrido.
--
-- Tres cosas:
--   1. ARREGLA el bug que impedía comprobar más de una URL al día a mano.
--   2. Añade el estado "comprobando" para poder enseñarlo en la interfaz.
--   3. Permite decidir qué días corre el barrido automático.

-- =============================================================================
-- 1. Las comprobaciones manuales ya no chocan entre sí
-- =============================================================================
-- `sweep_runs` tenía `unique (client_id, run_date, trigger)`. La puse para que
-- un doble disparo no mandara el digest dos veces, pero se llevó por delante
-- algo que NO es un barrido diario: pulsar "Comprobar" en una URL suelta.
-- Resultado en producción (23-jul-2026): el primer clic del día funcionaba y
-- los cinco siguientes se abortaban en silencio, mientras la interfaz decía
-- "Comprobación lanzada". Parecía que la app se había colgado.
--
-- La regla correcta: solo el barrido PROGRAMADO es único por día. Lo manual
-- puede repetirse tantas veces como haga falta.
--
-- SQLite no sabe quitar una constraint de tabla, así que hay que recrearla.

create table if not exists sweep_runs_nuevo (
  id        text primary key,
  client_id text not null references clients(id) on delete cascade,
  run_date  text not null,
  trigger   text not null default 'scheduler'
    check (trigger in ('scheduler', 'manual', 'api')),
  status    text not null default 'running'
    check (status in ('running', 'done', 'partial', 'failed')),

  started_at    text not null,
  finished_at   text,
  watches_total integer not null default 0,
  watches_done  integer not null default 0,
  watches_error integer not null default 0,
  changes_found integer not null default 0,

  notified_at   text,
  notify_status text,
  notify_error  text
);

insert into sweep_runs_nuevo
  select id, client_id, run_date, trigger, status, started_at, finished_at,
         watches_total, watches_done, watches_error, changes_found,
         notified_at, notify_status, notify_error
  from sweep_runs;

drop table sweep_runs;
alter table sweep_runs_nuevo rename to sweep_runs;

create index if not exists idx_sweep_runs_client on sweep_runs(client_id, started_at desc);

-- Índice único PARCIAL: solo el barrido programado es uno por cliente y día.
-- Sigue evitando que un doble disparo del cron duplique el digest.
create unique index if not exists idx_sweep_scheduler_unico
  on sweep_runs(client_id, run_date) where trigger = 'scheduler';

-- =============================================================================
-- 2. Estado "comprobando", para que se vea que algo está pasando
-- =============================================================================
-- Sin esto, pulsar "Comprobar" no daba ninguna señal: la petición devuelve 202
-- y el trabajo ocurre en segundo plano. No había forma de distinguir
-- "trabajando" de "roto".
alter table watch_state add column checking_since text;

-- =============================================================================
-- 3. Calendario del barrido automático
-- =============================================================================
-- Vigilar en sábado, domingo o festivo casi nunca aporta: nadie publica ese
-- día y el aviso se lee el lunes mezclado con el resto.

-- Días de la semana en que corre. Formato ISO: 1=lunes … 7=domingo.
alter table client_settings add column sweep_weekdays text not null
  default '[1,2,3,4,5]';

-- Fechas concretas que se saltan ('YYYY-MM-DD'). Se precargan los festivos
-- nacionales de España; el resto se edita desde la interfaz.
alter table client_settings add column sweep_skip_dates text not null default '[]';

-- Resumen a Slack al terminar un barrido completo, aunque no haya cambios.
-- Distinto del digest de cambios: este dice "he mirado y esto es lo que hay",
-- y es lo que convierte el silencio en una señal fiable.
alter table client_settings add column sweep_summary_to_slack integer not null default 1;
