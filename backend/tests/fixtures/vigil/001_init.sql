-- Vigil — esquema inicial (SQLite)
--
-- Convenciones:
--   * PK = TEXT con uuid4 generado en Python (SQLite no trae gen_random_uuid).
--   * timestamps = TEXT ISO-8601 UTC ('2026-07-22T04:30:00Z'). Ordenan bien
--     lexicográficamente, que es lo único que necesitamos.
--   * Sin enums: CHECK constraints. Sin arrays ni jsonb: TEXT con JSON
--     (SQLite trae JSON1, así que json_extract() funciona si hace falta).
--   * client_id en TODA tabla de negocio: el aislamiento por cliente se
--     comprueba en el backend (guard_client_access), no con RLS.

PRAGMA journal_mode = WAL;   -- lecturas concurrentes durante el barrido
PRAGMA foreign_keys = ON;

-- =============================================================================
-- Tenencia + auth
-- =============================================================================

create table if not exists clients (
  id         text primary key,
  slug       text unique not null,
  name       text not null,
  country    text default 'ES',
  is_active  integer not null default 1,
  created_at text not null,
  updated_at text not null
);

-- Auth PROPIA (sin Supabase): password_hash con bcrypt.
-- No hay registro público: los usuarios los da de alta un admin.
create table if not exists users (
  id            text primary key,
  email         text unique not null,
  display_name  text,
  password_hash text not null,
  role          text not null default 'seo' check (role in ('admin', 'seo')),
  is_active     integer not null default 1,
  last_login_at text,
  created_at    text not null,
  updated_at    text not null
);

create table if not exists client_members (
  client_id  text not null references clients(id) on delete cascade,
  user_id    text not null references users(id) on delete cascade,
  created_at text not null,
  primary key (client_id, user_id)
);

-- =============================================================================
-- Configuración por cliente
-- =============================================================================

create table if not exists client_settings (
  client_id text primary key references clients(id) on delete cascade,

  -- El webhook es un SECRETO: se guarda cifrado (Fernet, prefijo 'v1:') y
  -- NUNCA se devuelve al frontend. La API expone slack_webhook_set (bool)
  -- y slack_channel_hint.
  slack_webhook_url  text,
  slack_channel_hint text,
  slack_enabled      integer not null default 0,

  digest_min_severity text not null default 'info'
    check (digest_min_severity in ('critical', 'warning', 'info')),

  -- JSON arrays.
  default_content_selector text,
  default_ignore_selectors text not null default
    '["nav","footer","header",".cookie-banner","#onetrust-consent-sdk","[aria-live]",".carousel"]',
  default_ignore_regexes text not null default
    '["\\d{1,2}[/-]\\d{1,2}[/-]\\d{2,4}","\\d{1,2}:\\d{2}(:\\d{2})?","(?i)\\bhace\\s+\\d+\\s+\\w+"]',

  -- NULL = el default del código. Ver app/services/http_headers.py: cambiar
  -- el UA puede tumbar la captura de un cliente entero (Cloudflare de
  -- fitgeneration.es da 403 a Chrome/131 y 200 a Chrome/126). Es configurable
  -- justo para poder arreglarlo sin desplegar.
  user_agent        text,
  max_concurrency   integer not null default 6,
  request_timeout_s integer not null default 20,
  crawl_delay_ms    integer not null default 300,

  updated_at text not null
);

-- =============================================================================
-- Watches (URLs vigiladas)
-- =============================================================================

create table if not exists watches (
  id        text primary key,
  client_id text not null references clients(id) on delete cascade,
  url       text not null,
  label     text,
  is_active integer not null default 1,

  -- Qué se vigila. Cada flag tiene UI y afecta al barrido (no decorativo).
  watch_seo     integer not null default 1,
  watch_content integer not null default 1,
  watch_links   integer not null default 0,
  watch_html    integer not null default 0,

  -- Override de la config del cliente. NULL = hereda.
  content_selector text,
  ignore_selectors text,   -- JSON array
  ignore_regexes   text,   -- JSON array

  muted      integer not null default 0,
  source     text not null default 'manual'
    check (source in ('manual', 'bulk', 'sitemap', 'csv')),
  created_by text references users(id),
  created_at text not null,
  updated_at text not null,

  -- Hace idempotentes el alta en bulk y la importación de sitemap.
  unique (client_id, url)
);
create index if not exists idx_watches_client_active on watches(client_id, is_active);

-- Estado ACTUAL de cada watch: 1 fila por watch, se UPDATEa cada noche.
-- Separado de `watches` para que el barrido escriba aquí sin tocar config.
create table if not exists watch_state (
  watch_id  text primary key references watches(id) on delete cascade,
  client_id text not null references clients(id) on delete cascade,

  last_checked_at    text,
  last_changed_at    text,
  last_status_code   integer,
  last_final_url     text,
  last_error         text,
  consecutive_errors integer not null default 0,

  -- Se compara hash antes de calcular diffs caros o guardar cuerpos.
  hash_seo     text,
  hash_content text,
  hash_links   text,
  hash_html    text,

  -- Última extracción normalizada = "versión anterior" del diff SEO.
  -- El histórico completo se reconstruye desde change_items, así que no hace
  -- falta una fila de snapshot por día.
  seo_json   text,   -- JSON
  links_json text,   -- JSON

  -- status 200 + texto extraído casi vacío ⇒ la página probablemente necesita
  -- render JS. Se avisa en la UI; el renderer no existe todavía.
  needs_js_render integer not null default 0,

  last_snapshot_id text,
  updated_at       text not null
);
create index if not exists idx_watch_state_client on watch_state(client_id, last_changed_at desc);

-- =============================================================================
-- Barridos
-- =============================================================================

create table if not exists sweep_runs (
  id        text primary key,
  client_id text not null references clients(id) on delete cascade,
  run_date  text not null,               -- 'YYYY-MM-DD' UTC
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
  notify_status text,   -- sent | failed | skipped_no_changes | disabled
  notify_error  text,

  -- Un barrido programado por cliente y día. Con SQLite + una sola réplica
  -- esto es casi redundante, pero evita que un doble disparo manual duplique
  -- el digest.
  unique (client_id, run_date, trigger)
);
create index if not exists idx_sweep_runs_client on sweep_runs(client_id, started_at desc);

-- Solo fallos. Un barrido sano no escribe aquí.
create table if not exists run_errors (
  id          text primary key,
  run_id      text not null references sweep_runs(id) on delete cascade,
  client_id   text not null references clients(id) on delete cascade,
  watch_id    text references watches(id) on delete cascade,
  kind        text not null,   -- fetch_timeout | http_error | ssrf | parse |
                               -- storage | host_circuit_open
  message     text,
  status_code integer,
  created_at  text not null
);
create index if not exists idx_run_errors_run on run_errors(run_id);

-- =============================================================================
-- Snapshots — se escriben SOLO cuando algo cambió
-- =============================================================================
-- Si nada cambió, el último cuerpo guardado ES byte a byte el de hoy, así que
-- "guardar solo al cambiar" no pierde nada. Los cuerpos van comprimidos en
-- BLOB dentro del propio fichero SQLite: sin Storage externo, sin rutas que
-- se puedan quedar huérfanas.

create table if not exists snapshots (
  id          text primary key,
  watch_id    text not null references watches(id) on delete cascade,
  client_id   text not null references clients(id) on delete cascade,
  run_id      text references sweep_runs(id) on delete set null,
  captured_at text not null,

  content_hash text,
  html_hash    text,
  status_code  integer,
  byte_size    integer,

  -- gzip. NULL = ese cuerpo no se guardó en este snapshot.
  text_gz blob,
  html_gz blob,

  -- Texto sin comprimir si es pequeño (<32 KB). Evita descomprimir en el 90 %
  -- de páginas solo para calcular el diff de la noche siguiente.
  text_inline text,

  is_pinned integer not null default 0   -- exento de retención
);
create index if not exists idx_snapshots_watch on snapshots(watch_id, captured_at desc);

-- =============================================================================
-- Cambios
-- =============================================================================

create table if not exists changes (
  id               text primary key,
  client_id        text not null references clients(id) on delete cascade,
  watch_id         text not null references watches(id) on delete cascade,

  -- SET NULL, NO cascade. `changes` es el valor del producto: el histórico de
  -- qué tocó el cliente y cuándo. Los barridos, en cambio, son operativos y
  -- algún día habrá que purgarlos (crecen sin fin, uno por cliente y noche).
  -- Con cascade, esa purga se llevaría por delante el histórico en silencio.
  -- Un cambio huérfano de barrido sigue siendo perfectamente útil.
  run_id           text references sweep_runs(id) on delete set null,

  snapshot_id      text references snapshots(id) on delete set null,
  prev_snapshot_id text references snapshots(id) on delete set null,

  max_severity text not null check (max_severity in ('critical', 'warning', 'info')),
  detected_at  text not null,

  acknowledged_by text references users(id),
  acknowledged_at text,
  note            text,

  unique (watch_id, run_id)
);
create index if not exists idx_changes_client_detected on changes(client_id, detected_at desc);
create index if not exists idx_changes_watch on changes(watch_id, detected_at desc);

-- Detalle: un item por campo que cambió.
create table if not exists change_items (
  id        text primary key,
  change_id text not null references changes(id) on delete cascade,
  client_id text not null references clients(id) on delete cascade,

  kind     text not null check (kind in ('seo', 'content', 'links', 'html', 'availability')),
  field    text not null,   -- title | canonical | meta_robots | h1 | status_code | ...
  severity text not null check (severity in ('critical', 'warning', 'info')),
  rule_code text not null,  -- NOINDEX_ADDED | CANONICAL_CHANGED | ...

  before_val text,          -- truncado a 2000 chars para listados
  after_val  text,
  detail     text,          -- JSON, p.ej. {"added":[...],"removed":[...]}
  created_at text not null
);
create index if not exists idx_change_items_change on change_items(change_id);
