# CLAUDE.md - The Agency

> **IMPORTANTE:** Este archivo extiende las reglas globales. Lee primero `/Código/CLAUDE.md`

## Project Overview

**The Agency** es la plataforma unificada de gestion de agencia. Combina gestion operativa (clientes, proyectos, tareas, time tracking, equipo) con gestion financiera (ingresos, gastos, impuestos, previsiones). Multi-usuario con permisos por modulo.

- **Backend**: FastAPI (Python) con async SQLAlchemy + asyncpg (PostgreSQL)
- **Frontend**: React 19 + TypeScript + Vite + Tailwind CSS v4 + TanStack Query v5
- **Base de datos**: PostgreSQL 16
- **Puertos**: Frontend 5177 | Backend 8004

## Development Commands

### Prerequisitos
```bash
# Levantar PostgreSQL
docker compose up -d

# Primera vez: crear venv e instalar deps
cd backend && python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt
cd frontend && npm install
```

### Backend
```bash
source backend/venv/bin/activate
python -m backend.db.seed                        # Seed users + categories
uvicorn backend.main:app --reload --port 8004
```

### Frontend
```bash
cd frontend
npm run dev                        # Dev server on :5177
npm run build                      # tsc -b && vite build
npx tsc --noEmit                   # Type check only
```

Vite proxies `/api` requests to `localhost:8004` in dev mode.

### Seed Data
- Users: `david@magnify.ing` (admin), `nacho@magnify.ing` (member). Passwords via env vars `SEED_ADMIN_PASSWORD` / `SEED_MEMBER_PASSWORD`.
- 8 SEO task categories pre-seeded
- 8 expense categories pre-seeded

## Architecture

### Backend Structure
```
backend/
├── main.py              # FastAPI app, CORS, lifespan, router includes
├── config.py            # pydantic-settings loading from .env
├── api/
│   ├── deps.py          # get_current_user, require_admin, require_module
│   └── routes/          # All API route modules
├── core/security.py     # JWT create/decode, bcrypt hash/verify
├── db/
│   ├── database.py      # Async engine + session factory (PostgreSQL)
│   ├── models.py        # All SQLAlchemy models
│   └── seed.py          # Seed script
├── schemas/             # Pydantic schemas per entity
└── services/            # Business logic (tax, forecast, csv, advisor, etc.)
```

### Frontend Structure
```
frontend/src/
├── App.tsx              # Router + providers + routes
├── context/auth-context.tsx  # AuthProvider with permissions
├── lib/
│   ├── api.ts           # Axios + typed API functions
│   ├── types.ts         # TypeScript interfaces
│   └── utils.ts         # cn() helper
├── components/
│   ├── ui/              # Reusable (Button, Input, Dialog, Table, Badge...)
│   ├── layout/          # AppLayout, ProtectedRoute
│   ├── finance/         # Financial components
│   └── ...              # Feature-specific components
└── pages/               # All page components
```

### Key Patterns
- JWT auth via `Depends(get_current_user)` on all routes
- Module-based permissions via `require_module(module_name)`
- Admin role bypasses permission checks
- Client DELETE is soft delete (status=finished). En la UI es **"Antiguo"**: fuera de la cartera, alertas e importaciones, con todo su historial; se reactiva desde la ficha o la lista (`components/clients/client-lifecycle.tsx`). El borrado duro (`/hard`) es otra cosa e irreversible
- Eager loading (`lazy="selectin"`) for denormalized responses
- TanStack Query for server state, React Context for auth
- Path alias: `@/` -> `src/`

## Permission Modules
```
dashboard, clients, projects, tasks, timesheet, proposals,
reports, growth (Pipeline + Buffer), communications, digests, credentials (Accesos),
web (Webs: disponibilidad),
finance_income, finance_expenses, finance_taxes, finance_forecasts,
finance_advisor, finance_import, finance_dashboard,
admin_users, admin_settings
```

## Environment Variables (.env)
- `DATABASE_URL` - PostgreSQL connection (default: postgresql+asyncpg://agency:agency@localhost:5432/the_agency)
- `SECRET_KEY` - JWT signing key
- `ACCESS_TOKEN_EXPIRE_MINUTES` - Token TTL (default: 480)
- `DISCORD_WEBHOOK_URL` - Optional Discord webhook
- `ANTHROPIC_API_KEY` - API key for Claude (weekly digests generation)

## Weekly Digests (Claude AI)
- Collector: `backend/services/digest_collector.py` — recopila datos crudos (tareas, comunicaciones, tiempo)
- Generator: `backend/services/digest_generator.py` — genera contenido via Claude API (anthropic==0.49.0)
- Renderer: `backend/services/digest_renderer.py` — render a Slack (emoji text), Discord (MD), Email (HTML Magnify branded)
- API: `backend/api/routes/digests.py` — CRUD completo + generate + generate-batch + render
- Frontend: pages `digests-page.tsx` (lista) y `digest-edit-page.tsx` (editor con preview)
- Estructura contenido: `{greeting, date, sections: {done, need, next}, closing}`
- Tonos: formal | cercano | equipo
- Títulos sección: 1ª persona singular (cercano/formal), plural (equipo)
- Closing soporta HTML en email (para links tipo Google Sheets)
- **Flujo**: Generar → Editar → Copiar al portapapeles → Pegar en Gmail/Slack manualmente
- NO se envían emails ni mensajes desde la app. Discord solo para uso interno.
- **Vista "Resúmenes de este mes"** (`components/digests/digest-monthly-cycle.tsx`,
  arriba en `/digests`): una fila por cliente externo activo con el informe
  mensual encendido y el estado de su informe del mes anterior. Entregado = entrega externa confirmada
  (`digest_external_delivery_events`); `DigestStatus.sent` es histórico y no
  cuenta. Sin endpoint propio: lee `generation-preview` (Equipo para admins) y
  genera con `generate-cohort`, guardando la clave de recuperación como cohorte.

## Buffer de Ideas (Growth)
- **Concepto**: Backlog de ideas **por proyecto**, priorizadas con ICE (Impact/Confidence/Ease)
- **Flujo**: Idea → Puntuar ICE → Convertir a Tarea o Proyecto
- **Backend**: tabla `growth_ideas` con `project_id` FK, rutas en `/api/growth`, módulo `growth`
- **Frontend**: página `/growth` (Buffer global con filtro por proyecto) + tab "Buffer" en detalle de proyecto
- **Nomenclatura**: UI dice "Buffer de Ideas" / "Buffer", código interno sigue usando `growth` (evita migración DB)
- **No confundir** con Pipeline/Leads (`/leads`) que es el CRM comercial

## Semáforo SEO (tráfico orgánico por cliente)
- **Datos**: nuestro Search Console (`gsc_daily` de `Client.gsc_url`), NO The
  Engine. Clics e impresiones se suman en la MISMA ventana que el estado del
  cliente y Control SEO: `seo_window` (28 días hasta `gsc_site_sync.last_data_date`
  y los 28 anteriores). Sólo propiedades con histórico importado (`backfilled_at`).
  Sin columnas ni snapshots propios.
- **Cálculo**: `backend/services/seo_traffic.py`, una sola agregación SQL
  (`site_totals` / `client_traffic`, desfases sacados de `seo_window`) + la regla
  en Python (`trend_of`). `site_url_expr` es el gemelo SQL de
  `normalize_site_url` (una URL escrita sin barra final casa igual).
  `ClientResponse` expone `seo_clicks_change_pct`, `seo_impressions_change_pct`,
  `seo_trend` (`up`/`stable`/`down`/`drop_alert`; ±5 % es estable): no son
  columnas, los rellena `attach_seo_traffic` en la lista y en `GET /{id}` (en el
  resto de respuestas van a null). Sin propiedad o sin datos → null.
- **Lista de clientes**: columna "Tráfico SEO" ("Sin Search Console" sin
  propiedad); ordenar va al servidor (`GET /api/clients?sort=seo_change_asc|seo_change_desc`,
  `outerjoin` con `client_traffic`) para que los que más caen salgan primero en
  todas las páginas; sin base o sin propiedad, al final.
- **Estado del cliente** usa lo mismo (`traffic_by_site`): lista, incidencia y
  estado dan la misma cifra.
- **Incidencia**: `client_seo_traffic_drop` en el inbox de incidentes existente
  (`services/incident_client_conditions.py`). Salta si los clics caen
  ≥ `SEO_DROP_ALERT_PCT` (20) con ≥ `SEO_DROP_MIN_CLICKS` (100) en el periodo
  anterior; crítica a partir del doble del umbral. Destinatarios: admins y
  responsables de proyectos activos/planificados del cliente con lectura de
  `clients`. Clave `...:open`: se resuelve sola al recuperarse y un descarte se
  mantiene mientras dure la misma caída.

## PDF del resumen (sustituye al PDF de The Engine)
- **Qué es**: "Descargar PDF" en el editor, en cada fila de `/digests` y en la
  página pública `/c/:token` (sólo resúmenes entregados). Contenido = el email
  que recibe el cliente (`render_email`): mismas secciones, mismos bloques SEO y
  GA4 pintados por `digest_seo` / `digest_ga4`, mismos interruptores
  `include_seo` / `include_ga4`. Sale de la versión GUARDADA (el editor guarda
  antes si hay cambios, como la vista previa).
- **Motor: fpdf2** (`services/digest_pdf.py`), que ya estaba fijado en
  `requirements.txt` por las propuestas. Python puro, sin paquetes de sistema
  en `python:3.12-slim`: cero cambios en el Dockerfile. Se descartó WeasyPrint
  (pango/cairo por apt) y convertir el HTML del email (xhtml2pdf pinta mal sus
  tablas y añade dependencias): el PDF se monta con código desde los mismos
  datos y helpers del email, en A4 con márgenes, marca vectorial (la del
  favicon) y paleta Magnify.
- **Sin red**: ni imágenes ni fuentes externas (Helvetica de serie, cp1252: los
  emojis se quitan). `_OfflinePDF.image()` lanza error, porque fpdf2 descarga
  con `urlopen` si recibe una URL. El cierre (HTML) se reduce a texto, saltos,
  negritas y enlaces `http(s)`/`mailto`. Lo guarda `tests/test_digest_pdf.py`.
- **API**: `GET /api/digests/{id}/pdf` (mismas reglas que verlo:
  `authorize_digest`; 10/min por usuario) y
  `GET /api/public/clients/{token}/digests/{id}/pdf` (sólo la versión entregada
  que enseña la página; todo lo demás el mismo 404; 10/min por IP; cabeceras
  `noindex`/`no-store`/`no-referrer`). `application/pdf`,
  `informe-<cliente>-<AAAA-MM>.pdf`, `Cache-Control: no-store`.
- Se genera en `asyncio.to_thread` con 20 s de techo (504 si se agota).

## The Engine (congelado)
- **Congelado el 21 oct 2026** (decisión de David): sigue encendido, pero no se
  trabaja en él y **nada de The Agency depende de él**. Ni el semáforo, ni el
  orden de la lista, ni la incidencia de caída, ni el estado del cliente, ni el
  dashboard leen `engine_summary_data` ni ningún `engine_*`.
- **Lo que sigue enlazando a Engine** (sólo si el cliente tiene
  `engine_project_id`): pestaña "Engine" (`?tab=seo`), botón "Abrir en Engine" de
  la ficha, badge "Engine" de la lista, `EngineMetricsWidget` del Panel. El PDF del
  resumen ya es propio (ver "PDF del resumen"). `engine-config` sólo se pide si hay un cliente vinculado.
- **Sigue corriendo**: el job `engine` (copia el summary en `clients.engine_*`
  para esas pestañas) y las rutas proxy `api/routes/engine_integration.py`.
- Retirarlo del todo (job, rutas, columnas `engine_*`) es la fase 3 de
  `tasks/current/2026-10-21-web-y-control-seo/engine-revision.md`. No añadas
  nada nuevo que lea Engine.

## Ciclo mensual de resúmenes (fase 1 Agency 2.0)
- **Política por cliente** (`client_report_policies`): dos interruptores
  independientes, `monthly_enabled` (Informe mensual, mes natural anterior) y
  `weekly_enabled` (Seguimiento semanal, última semana lunes-domingo cerrada).
  Un cliente puede tener los dos; un solo responsable y una sola revisión.
  Nada encendido por defecto. La cadencia de un resumen sale de su periodo
  (`digest_periods.period_cadence` / `period_cadence_sql`): `weekly_digests` no
  guarda cadencia. `generation-preview` da una fila por cadencia encendida y
  la cohorte se identifica por (cliente, periodo). Las columnas antiguas
  `enabled`/`cadence` (una sola cadencia) se rellenaron en
  `report_policy_cadences_v1` y se retiraron en
  `report_policy_legacy_retirement_v1` (21 oct 2026). `ReportCadence` sigue
  vivo: es la cadencia de un periodo en la API de resúmenes.
- **`report_pending`**: uno por cada (cliente, cadencia) encendida sin versión
  de su periodo. Sólo un pendiente MENSUAL tapa el `report_unsent` del cliente.
- **"Entregado" = evento de entrega externa** (`digest_external_delivery_events`,
  botón "Marcar como entregado al cliente" del editor): guarda quién y cuándo.
  `DigestStatus.sent` es una etiqueta histórica sin evidencia: no cuenta.
- **Incidencia `report_unsent`** (`services/incident_report_conditions.py`): desde
  el día 1, por cada cliente externo activo con el informe mensual encendido cuyo
  mes anterior no tiene ninguna versión con entrega confirmada. Destinatarios:
  admins y el responsable de la política (con escritura en `digests`). Al
  responsable no le llega mientras tenga `report_pending` (aún no hay versión).
  Se resuelve sola al confirmar la entrega; clave por mes, así que el mes
  siguiente la sustituye.

## Undo (deshacer los últimos cambios)

- **Qué es**: los 5 últimos cambios de CADA usuario, deshacibles desde el panel
  ↶ de la barra lateral o con ⌘Z / Ctrl+Z.
- **Una entrada = una acción**, no una fila. Borrar un proyecto que además
  desvincula 8 tareas es UN "Deshacer", no nueve.
- **Captura**: `backend/services/change_journal.py`, con eventos de sesión de
  SQLAlchemy (`before_flush` / `after_flush` / `after_commit`). Ninguna ruta
  llama a nada, así que un endpoint nuevo queda cubierto solo.
- **Alcance**: Task, Project, Client, Lead, GrowthIdea + sus hijos propios
  (ProjectPhase, TaskChecklist, LeadActivity), que viajan en la misma entrada
  porque se borran en cascada con el padre. Finanzas queda FUERA (ver "No tocar").
- **Sólo se registra si hay actor** (`set_actor()` desde `get_current_user`).
  Barridos nocturnos, seeds y scripts no ensucian el historial de nadie.
- **API**: `GET /api/changes/recent`, `POST /api/changes/{id}/undo`
  (`backend/api/routes/changes.py`). Cada uno deshace lo suyo y se revalida el
  permiso de escritura del módulo en el momento del undo.
- **Conflictos**: si otra persona tocó después una columna, esa columna NO se
  restaura y se avisa en el toast. Deshacer nunca pisa el trabajo de otro.
- **Frontend**: `hooks/use-undo.ts` (compartido por panel y atajo),
  `components/layout/undo-panel.tsx`. Tras deshacer se invalida toda la caché de
  TanStack Query a propósito: un cambio puede haber tocado varias entidades.
- **Qué NO cubre**: los `UPDATE`/`DELETE` masivos hechos con `sqlalchemy.update()`
  / `delete()` no pasan por la capa ORM y no disparan los eventos. El purgado
  duro de clientes (`DELETE /api/clients/{id}/hard`) es de ese tipo y es
  irreversible por diseño.

## Procedimientos en tareas recurrentes
- La plantilla (`is_recurring`) guarda `procedure_text` + `procedure_url` y su
  checklist hace de checklist modelo. El generador (`services/recurrence.py`)
  copia ambos en cada repetición nueva (checklist sin marcar y sin fechas).
- Copia, no lectura en vivo: editar la plantilla sólo cambia las futuras.
- Sólo se escribe en la plantilla (`_validate_procedure` en `domain_writes.py`);
  en la repetición se muestra en lectura. Detalle en `docs/recurrences.md`.

## Borrador con IA desde el procedimiento (fase 3)
- En una repetición con procedimiento escrito, "Generar borrador" del panel llama
  a `POST /api/tasks/{id}/draft` (escritura en `tasks`; 422 sin `procedure_text`;
  `ai_limiter` 5/5 min). Servicio: `services/task_draft.py`.
- Prompt acotado: pasos, checklist, enlace del documento (no se descarga), título,
  descripción, proyecto y cliente; `Client.context` sólo si quien pide lee `clients`
  y el último resumen con entrega externa confirmada sólo si lee `digests` (el
  borrador lo ven todos los lectores de la tarea).
- Se guarda como comentario con `task_comments.is_ai_draft` (migración
  `task_comment_ai_draft_v1`): "Borrador de IA — revisar antes de usar", quién y
  cuándo. No toca estado, checklist ni nada externo. Si Claude falla: 502 y nada guardado.
- `claude-opus-5-5`, effort medium, `max_tokens` 8000, timeout 100 s sin reintento,
  dentro de los 120 s del front (lo guarda `tests/test_task_draft.py`).
- MCP: `draft_task(task_id)`.

## MCP (manejar The Agency desde Claude)

- **Qué es**: servidor MCP local por stdio en `mcp-server/` (paquete
  `agency_mcp`, Python >= 3.11, venv propio). Instalación y uso en
  `mcp-server/README.md`.
- **Es un cliente de la API**, como la extensión: entra con el usuario de la
  persona (`AGENCY_EMAIL` + contraseña en el Llavero o `AGENCY_PASSWORD`) y
  manda Bearer. Permisos por módulo y Deshacer funcionan solos. Cero cambios
  en el backend.
- **Si cambias un endpoint que usa** (tasks, tasks/{id}/draft, agenda, timer, time-entries,
  inbox, search, projects, users, auth/me, dailys + reparse + send-discord,
  clients/{id}/status (incluidos sus bloques `uptime` y `web_changes`),
  digests + external-delivery-events, web/uptime, clients/{id}/web/uptime-targets,
  web/changes), revisa `mcp-server/agency_mcp/server.py` y `format.py`.
- **Webs**: `web_status` (sólo lectura) junta disponibilidad y cambios sin
  revisar de un cliente, o el resumen global (caídas/bloqueos ahora y clientes
  con críticos sin revisar). Sin permiso de `web` lo explica en vez de dar un 403.
  Nada de Search Console ni GA4 (lo vigila `test_gsc_detail.py`).
- **Dailys**: `POST /api/dailys` sólo guarda; `submit_daily` encadena el
  `reparse` (90 s, como la web). `send_daily_to_discord` es la única
  herramienta que publica fuera (anotación `PUBLISH`) y sólo con dailys propios.
- **Sin herramientas de borrado**, a propósito.
- **Sin Accesos**, a propósito: ninguna herramienta lee `/api/credentials` ni
  devuelve contraseñas. No la añadas.
- MCP SDK v2: `FastMCP` ahora es `MCPServer` (`mcp.server.mcpserver`).

## Search Console propio (resúmenes mensuales)

- **Qué es**: The Agency importa Search Console por su cuenta (no depende de
  The Engine). Una o varias cuentas de Google, conectadas por un admin en
  Ajustes → Search Console (`gsc_connection`, una fila por cuenta, email
  único). Propiedad por cliente en `Client.gsc_url`; cada pasada mira qué
  cuenta ve cada propiedad (gana la de más permiso) y la guarda en
  `gsc_site_sync.connection_id`. Una cuenta caída se marca para reconectar
  sin parar a las demás.
- **Datos**: `gsc_daily` (totales diarios FINALES por propiedad, sin límite de
  16 meses), `gsc_site_sync` (hasta qué día hay datos, último error),
  `gsc_connection` (una fila por cuenta, token cifrado). Job diario `gsc`: 16 meses de
  backfill la primera vez, luego los últimos 7 días.
- **Resúmenes**: sólo los de MES NATURAL llevan `raw_context["seo"]` (lo añade
  el collector desde la BD propia, así las dos recolecciones coinciden). Si el
  mes no tiene datos finales hasta su último día → `status: "incomplete"` y no
  hay bloque. El bloque lo pinta `services/digest_seo.py` con código en email,
  Slack, Discord y texto plano: la IA no redacta esas cifras.
  `content.include_seo` permite quitarlo desde el editor.
- **Cifras**: clics/impresiones se suman; posición ponderada por impresiones;
  `position_delta` positivo = mejora.
- **Producción necesita** (una vez, en Google Cloud del cliente OAuth): activar
  la Search Console API, añadir el redirect `https://agency.magnifytools.com/api/gsc/callback`
  y el scope `webmasters.readonly` en la pantalla de consentimiento.
- **Desconectar** (`POST /api/gsc/connections/{id}/disconnect`, sólo admin):
  borra la fila y su token y DESPUÉS revoca en Google
  (`services/google_oauth.revoke_token`, 10 s, nunca lanza). Si Google no lo
  confirma, se desconecta igual y la respuesta lleva `google_revoked: false`
  para que el front lo diga. Con `{"purge_data": true}` (casilla del diálogo)
  borra además `gsc_daily`/`gsc_site_sync` y `ga4_daily`/`ga4_property_sync` de
  las propiedades cuyo `connection_id` era esa cuenta; si otra cuenta las ve, la
  siguiente pasada las reimporta desde cero. `delete()` masivo: fuera del Deshacer
  a propósito. Ojo: Google revoca el permiso ENTERO de esa cuenta para la app
  (mismo `GOOGLE_CLIENT_ID` que Calendar).
- **Detalle por consulta y página (Control SEO, PR1)**: job `gsc_detail`
  (lock **17**; 15/16 son de Webs; diario, timeout 1 h, misma puerta OAuth que
  `gsc`) → `services/gsc_detail_service.py`. Tablas `gsc_query_daily` y
  `gsc_page_daily` (PK sitio+día+consulta/página; página recortada a 2.000
  caracteres) y `gsc_detail_sync` (estado + filas guardadas), migración
  `gsc_detail_v1`. NO elige cuenta: usa `gsc_site_sync.connection_id` (lo decide
  el job `gsc`); sin cuenta válida apunta `pending_access`/`no_access` y sigue.
  Primera vez 120 días en tramos de 14; luego los últimos 7 (como `TAIL_DAYS`).
  Por tramo y dimensión: llamada a Google sin transacción y después borrar el
  tramo + insertar en lotes de 5.000 (reemplazo, no upsert: así desaparecen las
  consultas que ya no salen). Paginación de 25.000 filas con 0,2 s entre páginas.
  `POST /api/gsc/detail-sync` (admin) lo lanza a mano tomando el mismo lock (409
  si hay una pasada en marcha); `/api/gsc/status` trae `detail` por propiedad.
- **Retención del detalle (es lo que promete la política)**: se borra lo de más
  de 120 días antes del último día con datos (si la propiedad se para, la
  ventana avanza con el calendario, 7 días de margen) y todo lo de webs que
  ningún cliente activo sigue (cliente Antiguo o `gsc_url` cambiada). Corre en
  cada pasada, haya cuenta conectada o no. Desconectar con `purge_data` borra
  también el detalle de esas propiedades.
- **Historial mensual por consulta (más allá de los 120 días)**: tabla
  `gsc_query_monthly` (PK sitio+consulta+mes, mes = día 1 con CHECK;
  `weighted_position_sum` = SUM(posición × impresiones) para recalcular la
  posición ponderada), migración `gsc_query_monthly_v1` (añade también
  `gsc_detail_sync.monthly_backfilled_at`). Tras cada pasada del detalle,
  `sync_monthly` (en `gsc_detail_service.py`): (1) si la marca es NULL, pide a
  Google UNA vez cada mes del historial (16 meses contando el actual,
  `history_floor`) que el detalle diario no tiene entero, un mes por petición
  (`dimensions: ["query"]`, paginado de 25.000); un `GscSiteError` se apunta en
  el log y se reintenta al día siguiente sin bloquear el Control SEO (los de
  cuenta suben como siempre); (2) resume en SQL cada mes COMPLETO del detalle
  diario (borra el mes e inserta: idempotente). "Completo" = todos sus días
  desde `coverage_start` (el primer día guardado de consultas o el siguiente al
  que borra la retención, el más tardío) y con datos finales hasta su último
  día (`last_data_date`). En tests, el fixture autouse `_no_real_gsc_monthly`
  sustituye `query_month` (nunca sale a la red).
- **Retención del historial**: se borra lo anterior a `history_floor(hoy)` y,
  como el detalle, todo lo de webs sin cliente activo; desconectar con
  `purge_data` también lo borra (y la marca, así que se reimporta si otra
  cuenta ve la web).
- **Dos trampas al leer el detalle**: (1) Google anonimiza las consultas poco
  frecuentes, así que la suma de consultas < total de `gsc_daily`; "sin
  clasificar" = total − suma de consultas. (2) Las impresiones por página NO
  suman el total de la propiedad (una búsqueda que enseña dos páginas cuenta en
  las dos): el total sale siempre de `gsc_daily`.
- **El detalle no va a la IA**: ni resúmenes, ni borradores, ni asesor, ni
  enlace del cliente, ni MCP. Lo vigila `test_el_detalle_de_search_console_no_llega_a_la_ia`
  (`tests/test_gsc_detail.py`). Si lo cambias, cambia antes la política.
- El PDF ya no es el de The Engine (congelado; el enlace se quitó el 21 oct
  2026): ver "PDF del resumen". Su `report-data` tampoco se usa: traga errores
  como ceros y no pondera la posición.

## Control SEO por cliente

- **Qué es**: pestaña "Control SEO" de la ficha (área Resultados, sólo si el
  cliente tiene `gsc_url`). Lee lo que importan los jobs `gsc` (totales) y
  `gsc_detail` (consultas y páginas, 120 días). La pestaña de The Engine se
  llama ahora "Engine" y conserva la clave `?tab=seo`.
- **API** (lectura de `clients`, mismo 404 que `/{id}/status`;
  `api/routes/client_seo.py` → `services/seo_control.py`):
  `GET /api/clients/{id}/seo?days=7|28` (totales, marca/sin marca/sin
  clasificar + 16 semanas, secciones, 5 que más suben/bajan),
  `/seo/queries` y `/seo/pages` (`sort=clicks_gain|clicks_loss|position_gain|position_loss`,
  `brand` sólo en consultas, `section` sólo en páginas, `q`, `min_impressions`
  (30; por posición vale en las dos ventanas, por clics en la mayor), `limit` ≤ 100).
  `status`: `no_property | not_connected | reconnect_required | not_synced | backfilling | error | ok`.
- **Ventana**: `seo_window(end, days)` es el MISMO helper que usa
  `client_status._gsc_windows` (28 días; la anterior, los 28 de antes). Aquí
  `end` = el último día que tienen a la vez `gsc_site_sync` y `gsc_detail_sync`.
  Una agregación por tabla sobre el rango de la PK con `SUM(...) FILTER`.
  Caché en proceso de 1 h por (propiedad, final, días, pasada de los jobs); la
  marca se aplica después, así que cambiar los términos se ve al momento.
- **Marca**: `clients.brand_terms` (JSONB, migración `client_brand_terms_v1`,
  ≤ 20 términos de 3–60 caracteres, recortados y sin duplicados tras
  normalizar). Una consulta es de marca si contiene un término por SUBCADENA
  (sin regex), sin acentos ni mayúsculas, con o sin espacios. Se edita en
  Configuración del cliente (chips + "Sugerir", que sólo propone). Entra en el
  Deshacer como cualquier cambio del cliente.
- **Sin clasificar** = total de `gsc_daily` − suma de consultas (nunca < 0):
  son las búsquedas que Google oculta.
- **Secciones**: primer tramo de la ruta (decodificado, en minúsculas; un
  fichero suelto cuenta como sección; ruta vacía = "Inicio"; en propiedades de
  dominio, otros subdominios se agrupan por host; en las de prefijo, la ruta
  cuenta desde el prefijo). Reparto por CLICS: las impresiones por página no
  suman el total, sólo se enseñan en absoluto.
- **Historial de posiciones**: `GET /seo/queries/history?query=` → meses
  guardados (hasta 16, sólo completos; un mes con datos de la web pero sin esa
  consulta sale con 0 clics y posición null) + un punto por día del detalle
  (desde el primer día guardado, días sin fila = 0). `monthly_backfilled`
  dice si ya se trajeron los meses antiguos. `/seo/queries` y el resumen
  añaden `trend` (posición de los últimos 6 meses guardados) y `trend_months`.
  UI: pulsar una consulta abre `seo-query-history.tsx` (recharts, posición en
  eje invertido) y la columna "N meses" pinta la miniatura.
- **Grupos de URL**: `clients.seo_page_groups` (JSONB, migración
  `client_seo_page_groups_v1`), lista ordenada de `{name, rules: [{type:
  prefix|contains|regex, value}]}`; ≤ 30 grupos, ≤ 20 reglas, nombre 1–60
  único y nunca "Sin grupo", valor ≤ 200 (`clean_page_groups`). Se guarda con
  el PUT del cliente (`_UPDATABLE_CLIENT_FIELDS`), así que entra en el Deshacer.
  Una página va al PRIMER grupo que la acepta; si ninguno, "Sin grupo".
  `prefix` mira la ruta (como las secciones; con `http…` mira la URL entera),
  `contains` la URL entera y `regex` la ruta, sin mayúsculas.
  **Regex sin timeout de `re`**: se validan al guardar (`regex_problem`): sin
  repeticiones anidadas, sin alternativas dentro de una repetición sin tope,
  sin referencias hacia atrás ni lookarounds y ≤ 2 repeticiones sin tope; y el
  reparto entero tiene un tope de 5 s (`PageGroupTimeout` → 422). API:
  `GET /seo/groups?days=` (mismas cifras que las secciones, en el orden
  guardado y con los grupos vacíos), `POST /seo/groups/preview` (prueba sin
  guardar, sólo lectura de `clients`) y `/seo/pages?group=`. UI: conmutador
  Secciones/Grupos en la pestaña y editor en Configuración
  (`seo-page-groups-editor.tsx`, con "Probar").
- **Fuera de la IA y del MCP a propósito** (política de privacidad): lo vigila
  `test_el_detalle_de_search_console_no_llega_a_la_ia`, que también prohíbe
  `seo_control`/`client_seo`, `gsc_query_monthly`, `seo_page_groups` y
  `query_history` en cualquier camino de IA.

## Estado del cliente (cartera)

- **Qué es**: la antigua salud 0-100 se sustituyó (19 oct 2026) por un estado
  explicado: `act` (Actuar) · `watch` (Vigilar) · `ok` (Bien) · `no_data`, con
  la lista de motivos. Vive en `backend/services/client_status.py`; API
  `GET /api/clients/portfolio` y `GET /api/clients/{id}/status`. La lista de
  clientes abre en la vista Cartera (`?vista=listado` para la tabla clásica) y
  la ficha muestra la misma tarjeta.
- **Señales** (umbrales en el propio módulo): tráfico de Google 28 días
  (`gsc_daily` propio vía `seo_traffic`; sin propiedad no hay señal, Engine ya
  no hace de respaldo), una señal por
  cadencia encendida en `ClientReportPolicy` (`digests`, mensual primero; toca /
  atrasado tras 5 días; cuenta sólo la entrega externa confirmada de un periodo
  de esa cadencia; `digest` = la peor, por compatibilidad), tareas vencidas (≥ 3 =
  Actuar; las tareas en espera no cuentan), seguimientos con el cliente
  vencidos y consumo de la cuota del mes (sólo admin, ≥ 90 % / ≥ 110 %).
- **No lee comunicaciones** (decisión de David): no añadas esa señal.
- Cada señal se calcula sólo si quien mira puede leer su fuente; sin ninguna
  señal el estado es `no_data`, nunca un "Bien" inventado.
- **Listo para entregar** (`ready`, sólo en `/{id}/status`, no en la cartera;
  pide leer tareas y resúmenes): tareas completadas (la revisión, si el proyecto
  la exige, ya pasó: sólo el responsable cierra) desde el inicio del periodo que
  toca entregar (semanal sólo si es la única cadencia encendida; si no, mensual) o desde el día tras
  el último periodo con entrega externa confirmada, lo más reciente. Sin columnas
  nuevas. Lo pinta el bloque Trabajo de la Vista general.

## Fila "Operación" del dashboard
- Cuatro cifras de HOY (no del mes elegido) en `/` bajo la visión general:
  `GET /api/dashboard/operations` → `services/operations_summary.py`. No hay
  pantalla ni módulo propio (el ejecutivo oculto no vuelve).
- Ninguna fórmula propia, cada cifra llama a quien ya decide esa regla:
  cuota recurrente = `services/recurring_fee.py` (SUM `Project.monthly_fee` de
  proyectos activos de clientes externos activos; sólo admin); proyectos en
  riesgo = `project_measure_rows` + `monthly_hours_usage` de
  `incident_project_conditions.py` (cierre vencido u horas del mes ≥ 100 %);
  clientes en Actuar = `client_status.portfolio`; resúmenes sin entregar =
  `unsent_monthly_clients` de `incident_report_conditions.py` (regla de
  `report_unsent`).
- Cada cifra es `null` si quien mira no lee su fuente; el front no la pinta.

## GA4 propio (visitas, conversiones y tráfico desde IA)

- **Qué es**: con las mismas cuentas de Google que Search Console (permiso
  `analytics.readonly`), el job diario `ga4` importa por propiedad
  (`Client.ga4_property_id`, se normaliza a sólo dígitos) sesiones, eventos
  clave (conversiones) y la parte que llega desde asistentes de IA
  (`AI_SOURCES` en `services/ga4_service.py`, por `sessionSource`).
  Tablas `ga4_daily` y `ga4_property_sync` (migración `ga4_v1`).
- **Cuentas**: la Admin API dice qué cuenta ve cada propiedad. Una cuenta
  conectada antes de pedir el permiso de Analytics da `missing_scope`: se
  apunta en la propiedad y la cuenta NO se marca para reconectar (Search
  Console sigue funcionando con ella); hay que reconectarla para dar permiso.
- **Uso**: la ficha enseña 28 días frente a los 28 anteriores (sólo se
  enseña, no es señal de estado). Los resúmenes de mes natural llevan
  `raw_context["ga4"]` y un bloque pintado con código (`digest_ga4.py`),
  quitable con `content.include_ga4`. Un mes cuenta como cerrado cuando se ha
  importado al menos 3 días después de su último día.
- **Producción necesita**: en Google Cloud, activar Google Analytics Data API
  y Google Analytics Admin API y añadir el scope `analytics.readonly` a la
  pantalla de consentimiento; luego reconectar cada cuenta en Ajustes.

## Vigil (cambios en las webs de los clientes)

- **Qué es**: Vigil (`/Código/Vigil`, vigil.magnifytools.com) vigila cambios en
  las páginas de cada cliente. The Agency lee su resumen con
  `GET /api/integrations/summary` y la cabecera `X-Service-Key`
  (`VIGIL_API_URL` + `VIGIL_SERVICE_KEY`, la misma clave que `VIGIL_SERVICE_KEY`
  en Vigil). Sin URL o sin clave, el job `vigil` queda en pausa.
- **Enlace**: `Client.vigil_slug` (Ajustes del cliente, único). El job copia un
  resumen por slug en `vigil_summary` cada 6 h. Cada 6 h y no diario, porque el
  turno diario sería antes del barrido de Vigil (04:30 UTC).
- **Uso**: la ficha lo enseña en Resultados y el estado del cliente da
  Vigilar si hay cambios críticos sin revisar. Un resumen de más de 48 h se
  enseña pero no cuenta (`services/vigil_service.py`).
- **Se retira** (decisión de David, 21 oct 2026): The Agency ya vigila cambios
  por su cuenta (ver "Webs: cambios"). Si un cliente tiene URLs propias en
  `web_watches`, su estado ya NO cuenta Vigil. La integración se quita en la
  fase 3, tras importar los datos; hasta entonces, no la borres.
- **Corte** (fase 3a): runbook en `docs/vigil-migration.md` (congelar Vigil,
  importar, calibrar sin Slack, encender `WEB_SWEEP_ENABLED`, y la retirada 3b/3c).
  `python -m backend.scripts.import_vigil --sqlite vigil.db --dry-run` copia
  `vigil.db` (sólo lectura) a las tablas `web_*` conservando los ids, en UNA
  transacción idempotente (`ON CONFLICT (id) DO NOTHING`); slug → `vigil_slug`
  (o `--map slug=id` / `--skip slug`; un slug sin pareja aborta todo), usuarios
  por email (si no, `acknowledged_by_label`), webhook re-cifrado con
  `encrypt_vault_secret` (`VIGIL_SECRET_KEY` por entorno o teclado, nunca por
  argumento) y lo que en Vigil era default entra como NULL. Lo de The Agency
  manda en `client_web_settings`. `python -m backend.scripts.web_calibrate`
  barre sin avisar a Slack (`notify=False`): se corre en Railway tras importar.

## Webs: disponibilidad (monitor de caídas, fase 1)

- **Qué es**: The Agency comprueba si responde cada URL vigilada de cada cliente
  (independiente de Vigil). Módulo de permisos `web` ("Webs"): leer = ver;
  escribir = gestionar URLs y "Probar ahora". El Slack del cliente, sólo admin.
  Código en `backend/services/web/` (`uptime.py`, `uptime_notify.py`,
  `uptime_views.py`, `safe_http.py`, `headers.py`, `slack.py`); API en
  `api/routes/web_uptime.py`; tablas `web_uptime_targets`, `web_uptime_state`,
  `web_outages`, `web_uptime_probes`, `client_web_settings` (migración `web_uptime_v1`).
- **Clasificación**: arriba = 2xx/3xx; caída = 5xx, 404/410 y demás 4xx,
  timeout, DNS, conexión, TLS, demasiadas redirecciones, IP no pública;
  **bloqueo ≠ caída** = 401/403/429 o desafío de Cloudflare (responde, pero no a
  nosotros). Bloqueo > `UPTIME_BLOCKED_ALERT_MINUTES` (60) abre una "caída" de
  tipo `blocked`: sólo aviso en la bandeja, nunca a Slack.
- **Umbrales** (settings): se mira cada `UPTIME_INTERVAL_SECONDS` (300); tras un
  fallo, `UPTIME_RECHECK_SECONDS` (60); `UPTIME_FAILURES_TO_ALERT` (2) ciclos
  fallidos = caída (empieza en el primer fallo); `UPTIME_RECOVERIES_TO_CLOSE` (2)
  ciclos buenos = recuperada. Un fallo se reintenta una vez a los 5-10 s dentro
  del ciclo. GET con cuerpo ≤ 64 KB, 15 s en total, ≤ 5 redirecciones.
- **Falsas alarmas**: canario `UPTIME_CANARY_URLS` al empezar (si ninguna
  responde, ciclo saltado y job `provider_unavailable`); correlación: ≥ 3 hosts
  y ≥ 50 % fallando por red (sin respuesta HTTP) en el mismo ciclo = red nuestra,
  no avanzan contadores. Cada host en serie, máx. 8 a la vez; User-Agent del
  cliente (`client_web_settings.user_agent`) o el de `headers.py`.
- **SSRF**: toda petición pasa por `safe_http.fetch` (DNS una vez, TODAS las IPs
  globales, IP fijada con SNI, cada redirección revalidada, sólo puertos 80/443,
  sin credenciales en la URL). Al guardar, `check_url_syntax` (sin red). No
  pidas una URL de cliente con `httpx` a pelo.
- **Avisos**: incidencias `client_site_down` (crítica) y `client_site_blocked`
  (aviso) en `services/incident_web_conditions.py`, clave
  `...:client:{id}:open`, huella con los ids de las caídas (un descarte vale para
  ESA caída). Destinatarios: admins y responsables de proyectos activos/planificados
  del cliente con lectura de `web`. Además, "web caída" y "web recuperada" (con
  duración) al **Slack de cada cliente** (webhook cifrado con
  `encrypt_vault_secret`, CHECK `v1:%`, nunca vuelve en una respuesta). Sin canal
  interno.
- **Slack como outbox**: la caída se guarda con `slack_down_status='pending'` en
  la misma transacción que el estado; luego se publica y se anota. Lo pendiente se
  reintenta al empezar cada ciclo (10 intentos). Webhook revocado (404/410) →
  `slack_enabled=false` + `slack_revoked_at`.
- **Estado del cliente**: caída = Actuar ("La web no responde desde …"), bloqueo
  largo = Vigilar; bloque `uptime` en `/status` y `/portfolio`, sólo si quien
  mira lee `web`.
- **Job** `uptime`: lock **15** (16 reservado para `web_sweep`, 17 para
  `gsc_detail`), cada 60 s, timeout 150 s, sólo clientes activos no internos.
  **Apagado por defecto**: en Railway `UPTIME_ENABLED=true`. Sondeos 30 días
  (`_retention_cleanup_once`); las caídas se conservan.
- Fuera del Deshacer (`test_webs_quedan_fuera_del_journal`). Alta inicial:
  `python -m backend.scripts.seed_uptime_targets --dry-run|--apply` (home desde
  `Client.website`).

## Webs: cambios (vigilancia de cambios, fases 2a y 2b)

- **Qué es**: Vigil portado dentro de The Agency. Por cada URL vigilada de un
  cliente se compara SEO (title, description, H1/H2, canonical, robots meta +
  `X-Robots-Tag`, hreflang, schema), texto visible, enlaces y HTML normalizado
  con la última captura, y se avisa en el **Slack de cada cliente** (el mismo
  webhook cifrado del monitor de caídas). Mismo módulo de permisos `web`: leer =
  ver; escribir = URLs, "Comprobar ahora", previsualizar, ajustes de captura y
  calendario, y marcar como revisado. Pantallas: ver "Interfaz (fase 2b)" abajo.
- **Código** (`backend/services/web/`): `extractor.py`, `classifier.py`,
  `html_diff.py`, `capture_defaults.py`, `calendario.py`, `sitemap.py` y
  `digest.py` son copia casi literal de Vigil (mismas reglas: los cambios
  importados y los nuevos se leen igual). `sweep.py` está reescrito en
  SQLAlchemy async; `changes_views.py` son las lecturas. API:
  `api/routes/web_watches.py` (URLs, alta en bloque/CSV, sitemap, comprobar,
  progreso, previsualizar, historial), `web_changes.py` (lista global con
  filtros, detalle, `/diff`, `/html-diff`, revisar, revisar todo, barridos y sus
  errores) y `web_settings.py` (captura, calendario, festivos).
- **Tablas** (migración `web_changes_v1`): `web_watches`, `web_watch_state`,
  `web_sweep_runs`, `web_run_errors`, `web_snapshots` (cuerpos gzip en `bytea`,
  sólo cuando cambia un hash), `web_changes` (`run_id`/capturas `ON DELETE SET
  NULL`: purgar barridos no borra el histórico), `web_change_items`. **PK UUID**
  (excepción a la convención de enteros) para que la importación de Vigil
  conserve sus ids. `client_web_settings` gana `digest_min_severity`,
  `default_content_selector`, `default_ignore_selectors/regexes`,
  `max_concurrency`, `request_timeout_s`, `crawl_delay_ms`, `sweep_weekdays`,
  `sweep_skip_dates`, `sweep_summary_to_slack`: **sin DEFAULT**, NULL = el valor
  de `capture_defaults.py` (el contrato lo verifica). En Vigil el DEFAULT de la
  columna se quedó congelado con `[aria-live]` dentro y hubo que reescribir filas
  a mano: aquí corregir un default en código corrige a todos los que no lo
  personalizaron.
- **Job** `web_sweep`: lock **16**, cada 60 s, timeout 900 s, reintento 300 s.
  **Apagado por defecto** (`WEB_SWEEP_ENABLED=false`): sin él no corre ni el
  diario ni "Comprobar ahora" (la API lo dice en `enabled`). Cada ciclo: 1) recoge
  sin margen los barridos `running` y las marcas `checking_since` (tenemos el
  lock 16: nada más puede estar vivo); 2) lo pedido a mano (`check_requested_at`;
  si son TODAS las URLs del cliente es "comprobar todas" y avisa a Slack con
  resumen; una suelta no avisa); 3) a partir de `WEB_SWEEP_LOCAL_TIME` (06:30,
  Europe/Madrid), **un** cliente activo externo sin barrido programado hoy y al
  que el calendario (`toca_barrido`: lunes-viernes y festivos marcados) le toque.
  El índice único parcial `(client_id, run_date) WHERE trigger='scheduler'` es la
  guarda: el programado es uno por día; lo manual, los que hagan falta (lección
  0bis). Retención: barridos de más de 180 días en `_retention_cleanup_once`.
- **Reglas del barrido** (las de Vigil): una URL que falla no tumba el barrido
  (`web_run_errors`) ni un cliente a los demás; un fallo de Slack no invalida el
  barrido (`notify_status`/`notify_error`); primera captura = ningún aviso; sin
  cambios no se manda digest, pero el barrido completo manda su resumen ("he
  mirado 6, ninguna cambió") salvo que se apague; `muted` = se guarda pero no se
  avisa; `digest_min_severity` filtra lo que va a Slack. **Circuit breaker** por
  host (> 30 % de fallos con ≥ 4 URLs): ese host no se clasifica. Cuenta como
  fallo no responder Y un bloqueo 401/403/429/desafío (en Vigil un WAF con 403
  daba un crítico por URL). Se cruza con `web_uptime_state`: si el monitor dice
  caída, el aviso lo dice; si no, "probable bloqueo".
- **CPU en un hilo** (regla nueva): extraer, comparar, `difflib` y gzip van en
  `asyncio.to_thread` (`extract`, `compare`, html-diff, previsualización,
  sitemap). Este proceso es también la API: lxml sobre 300 KB o un diff
  cuadrático en el bucle de eventos la congelaría. La red y Slack, sin
  transacción abierta. Lo vigila `test_el_trabajo_de_cpu_va_en_un_hilo`.
- **Sin Playwright ni capturas de pantalla** (decisión de David): un Chromium
  por URL alarga el barrido de minutos a horas, resuelve DNS por su cuenta
  (reabre la SSRF que cierra `safe_http`) y pide binarios que la imagen
  `python:3.12-slim` no trae. Una página que necesita JS sale como
  `needs_js_render` (200 con < 25 palabras), no se renderiza.
- **User-Agent frágil**: el Cloudflare de fitgeneration.es da 403 a `Chrome/131`
  y 200 a `Chrome/126` (Vigil, 22-jul-2026). Mismo `headers.py` y mismo UA por
  cliente que el monitor de caídas: subir la versión de Chrome no es cosmético.
- **Incidencia** `client_web_critical_change` (crítica) en
  `incident_web_conditions.py`: abierta mientras haya cambios críticos sin
  revisar de URLs no archivadas ni silenciadas de clientes activos; se resuelve
  al revisarlos; huella con los ids de los cambios. Mismos destinatarios que las
  caídas. Enlace `/web/cambios?cliente={id}`.
- **Estado del cliente**: si tiene URLs propias (no archivadas), mandan ellas
  (crítico sin revisar = Vigilar; bloque `web_changes`, sólo si quien mira lee
  `web`) y Vigil deja de contar; si no, sigue el resumen de Vigil.
- **Lecciones de Vigil que siguen valiendo**:
  - *0quater*: un selector de poda mal elegido no hace ruido, hace SILENCIO
    (`[aria-live]` se comía 1.039 palabras). Antes de añadir uno, medir con
    `POST /api/web/watches/{id}/preview` (dice cuántas palabras se lleva cada
    selector). Los selectores y regex se validan al guardar (422).
  - *0quinquies*: `content_selector` acota texto, enlaces y HTML, no el SEO; si
    deja de casar se vigila la página entera y se enciende `scope_missed`.
  - *0sexies / 0nonies*: el estado de Slack se lee de la CONFIGURACIÓN
    (`slack_state`: `ready`/`disabled`/`revoked`), nunca del último barrido;
    "configurado" y "activo" no son lo mismo.
  - *0septies*: `/html-diff` compara el HTML NORMALIZADO (el del hash) y, si no
    puede, SIEMPRE trae `reason` (`sin_actual`, `sin_anterior`, `demasiado_grande`).
  - *0decies*: `HTML_CHANGED` lleva el tamaño (+N/−M líneas de T) en pantalla y
    en Slack; sin medida no se inventa un cero. Los contadores de la lista
    (`counts`, `counts_pending`) ignoran los filtros de severidad y de revisado, y
    `truncated` dice si el `limit` dejó cosas fuera.
  - *0octies* (Railway desplegaba un snapshot) no aplica: Agency despliega desde
    `main`.
- **Interfaz (fase 2b)**:
  - Pestaña **Web** de la ficha (`components/web/web-tab.tsx`): debajo de la
    disponibilidad, `web-watches-card.tsx` (URLs: alta suelta, lista/CSV y
    sitemap; silenciar, archivar/recuperar, "Comprobar ahora"/"Comprobar todas"
    con progreso cada 3 s mientras hay barrido vivo o cola; con el job apagado lo
    dice en vez de girar), cambios del cliente (`web-changes-list.tsx`, abre en
    "Sin revisar"), `web-runs-card.tsx` (últimos barridos, errores por URL, estado
    del aviso a Slack) y, sólo con escritura en `web`,
    `web-change-settings-card.tsx` (días, festivos, resumen a Slack,
    `digest_min_severity`, selectores/regex por defecto; vacío = default del código).
  - Ficha de una URL: panel lateral `watch-drawer.tsx` (estado, último error,
    `scope_missed`/`needs_js_render`, cambios, capturas, configuración y "Probar
    esta configuración", que prueba lo ESCRITO, no lo guardado).
  - `/web/cambios` (`pages/web-changes-page.tsx`, menú Clientes → "Cambios web")
    y `/web/cambios/:id` (`pages/web-change-detail-page.tsx`): son las rutas del
    digest de Slack y de la incidencia; no cambiarlas sin `services/web/digest.py`.
    Filtros en la URL (`cliente`, `sev`, `estado=todo`; sin `estado` = sin revisar).
  - Reglas de Vigil en pantalla: severidad y revisado son controles segmentados
    con recuento, y el recuento sale de `counts`/`counts_pending` (ignoran el
    filtro activo); "Marcar todo" confirma con el número del servidor y se acota a
    cliente + severidad; "Solo maquetación · +x/−y líneas de T" (sin medida, se
    dice; los miles con `formatInt`, porque es-ES no agrupa 4 cifras); el diff de
    HTML vacío explica su `reason`; el de texto es por frases (`sentenceDiff`, con
    tope de celdas: si no cabe, enseña los trozos guardados en `detail.diff`); el
    estado de Slack se lee de `slack` de la configuración, no del último barrido.
  - Query keys en `webKeys` (`lib/query-keys.ts`); revisar invalida listas y
    fichas (`invalidateWebReview`), nunca los diffs (inmutables).
- **Datos de Vigil**: se importan con `scripts/import_vigil.py` (ver sección
  Vigil y `docs/vigil-migration.md`). El `watch_state` importado es la "versión
  anterior" del primer barrido: sin él, todo saldría como primera captura.
- **Fuera del Deshacer** (`test_cambios_web_quedan_fuera_del_journal` y
  `test_nada_de_la_vigilancia_de_cambios_entra_en_el_deshacer`). Dependencias:
  `lxml` y `cssselect` (ruedas cp312 manylinux, sin compilar).

## Enlace para el cliente (fase 3 Agency 2.0)

- **Qué es**: página pública `/c/:token` (sin login, fuera del shell) con SÓLO
  los resúmenes entregados del cliente y sus clics/impresiones/posición de
  Google por mes. Nada de tareas, borradores ni notas. Se gestiona en Ajustes
  del cliente → "Enlace para el cliente" (`client-share-link-card.tsx`).
- **Token**: `secrets.token_urlsafe(32)`; en `client_share_links` sólo se guarda
  su SHA-256. El enlace completo se enseña UNA vez al crearlo; después, "activo
  desde…" y última visita (se apunta como mucho una vez por hora). Un enlace
  activo por cliente (índice único parcial); regenerar revoca el anterior.
  Revocar no entra en el Deshacer: el token no existe en ningún sitio.
- **API**: `GET/POST/DELETE /api/clients/{id}/share-link` (ver: lectura de
  `clients`; crear/revocar: escritura de `clients`, y crear pide además leer
  `digests`, porque el enlace los enseña). Pública: `GET /api/public/clients/{token}`
  (`api/routes/client_share_links.py`, `services/client_share_links.py`),
  limitada a 30/min por IP; desconocido, revocado o mal formado → el mismo 404.
  Cabeceras `noindex`, `no-store` y `no-referrer` (también en el HTML de `/c/`).
- **Qué resúmenes**: la regla de `report_unsent` (`delivery_is_confirmed`): la
  última acción de entrega externa es una confirmación. `DigestStatus.sent` NO
  cuenta. Una versión por periodo (la última entregada), pintada con
  `render_email` y mostrada en un iframe `sandbox` sin scripts.
- **Tráfico**: `gsc_daily` de `Client.gsc_url`, 16 meses naturales CERRADOS
  (hasta el último con datos hasta su último día, según `gsc_site_sync`).

## Páginas públicas /acerca y /privacidad
- Existen para la verificación de Google OAuth (página de inicio de la app y
  política de privacidad de los datos de Google). Sin login, fuera del shell:
  `frontend/src/pages/public-legal.tsx`. Enlazadas desde el login.
- **No se indexan**: meta robots en la página + `X-Robots-Tag` desde
  `spa_headers()` en `backend/main.py`. `robots.txt` las deja leer (Allow) para
  que el noindex se vea; el resto sigue en `Disallow: /`.
- **Lo que dicen tiene que ser verdad en el código**: qué se guarda de Search
  Console (totales, 120 días de detalle por consulta y página y un total
  mensual por consulta de hasta 16 meses), GA4 y Calendar, que nada de eso va a la IA, que desconectar borra el
  token y revoca en Google, que las cifras sólo se borran si el admin lo marca,
  que desconectar Calendar borra sus eventos importados y que los eventos de
  Google se borran 30 días después de terminar. Si cambias qué se lee o se
  guarda de Google, cambia la política en el mismo PR.

## Google Calendar: desconexión y retención
- `POST /api/calendar/disconnect`: borra el token, borra SIEMPRE los `events`
  con `source="google"` de esa persona (los manuales se quedan) y, tras el
  commit, revoca el token en Google con `google_oauth.revoke_token` (mismo
  criterio que Search Console: no bloquea; `google_revoked` en la respuesta).
- Retención: el job diario `retention` (`_retention_cleanup_once`) llama a
  `google_calendar_service.purge_past_google_events`: borra los eventos de
  Google cuyo fin (o inicio si no hay fin) es de hace más de 30 días, en hora
  civil de la agencia. Ambos borrados son `delete()` masivos: fuera del Deshacer
  (Event tampoco está en el journal).
- En tests, el fixture autouse `_no_real_google_revoke` (`backend/tests/conftest.py`)
  sustituye la revocación en las rutas: nunca sale a la red.

## Extensión de Chrome: descarga
- Ajustes → "Extensión de Chrome" (`components/settings/extension-section.tsx`):
  botón "Descargar extensión" con la versión desplegada y pasos para instalar
  (cargar descomprimida) o actualizar (sustituir la carpeta y recargar).
- `GET /api/extension` (versión) y `GET /api/extension/download` (zip), ambos con
  sesión. El zip lo arma el backend en memoria desde los ficheros de
  `chrome-extension/` que copia el Dockerfile (`services/extension_package.py`,
  `RUNTIME_FILES`), con la versión de su `manifest.json`: no hay artefacto a mano.
  Si añades un fichero a la extensión, añádelo a `RUNTIME_FILES` y al Dockerfile
  (lo vigila `tests/test_extension_download.py`).
- Nada de zips sueltos en la raíz (`.gitignore`). Al cambiar código de la
  extensión, sube la versión del `manifest.json`.

## Accesos (contraseñas compartidas)

- **Qué es**: `/credentials` (Ajustes → Accesos) y pestaña Accesos de la ficha
  del cliente (área Relación). Tablas `credentials`, `credential_shares`,
  `credential_access_log` (migración `credentials_v1`). Nada que ver con el
  "vault" `agency_assets` retirado en la fase 0.
- **Acceso por entrada**: módulo `credentials`. Admin ve y gestiona todo; el
  resto sólo lo que creó o le compartieron (lo demás es 404, no 403). Crear pide
  escritura; editar/compartir, además ser admin o quien lo creó; borrar
  (definitivo) sólo admin. Sólo se comparte con usuarios activos que pueden abrir
  el módulo.
- **Secreto**: cifrado en el servidor con `encrypt_vault_secret` (`VAULT_KEY`,
  o `SECRET_KEY` si falta). Un CHECK (`LIKE 'v1:%'`) impide guardar texto plano.
  Ningún listado lo devuelve: sólo `POST /api/credentials/{id}/reveal`
  (`purpose` reveal|copy), 30/min por usuario, `Cache-Control: no-store`, que
  apunta quién y cuándo ANTES de devolverlo. El front no lo guarda en la caché de
  TanStack y lo oculta a los 30 s. Las notas NO se cifran.
- **Registro**: `credential_access_log` (reveal, copy, create, update, share,
  delete; detalle de qué cambió o con quién). Sobrevive al borrado del acceso
  (`credential_id` a NULL + `credential_name`). Lo ve sólo un admin.
- **Fuera del Deshacer** a propósito: no está en `change_journal._SPECS` (el
  snapshot llevaría el secreto a `change_logs` y un undo podría resucitar una
  contraseña rotada). Lo guarda `test_accesos_quedan_fuera_del_journal`.
- **Fuera del MCP**: ver sección MCP.
- **Límite de seguridad**: el cifrado protege la BD y sus copias, no el
  servidor. Quien tenga a la vez la BD y `VAULT_KEY` (Railway) descifra todo.
  Rotar `VAULT_KEY` deja ilegibles los accesos existentes (no hay re-cifrado).

## No tocar
- Módulos financieros custom: tax_service, forecast_service, income, expenses, taxes, forecasts
- Se reemplazarán por integración Holded en fase posterior
- Si necesitas importar algo de estos módulos, no lo hagas. Trabaja alrededor.

## Pricing Architecture (Sprint 10)
- **Source of truth**: `Project.monthly_fee` — cada proyecto define su tarifa mensual
- **Client budget**: `Client.monthly_budget` es legacy/fallback. El presupuesto real se deriva de `SUM(Project.monthly_fee)` de proyectos activos
- **Dashboard**: `total_budget` agrega desde proyectos con fallback a `client.monthly_budget` cuando no hay proyectos
- **Onboarding**: Crear cliente + proyecto en un solo flujo. La extracción AI (extract-context) devuelve un sub-objeto `project` con `monthly_fee`
- **Profitability**: Ya calcula correctamente desde `Project.monthly_fee`

## Testing
```bash
# Backend (pytest; tests/integration contra Postgres real con TEST_DATABASE_URL)
cd backend && source venv/bin/activate && python -m pytest tests/ -v

# Frontend (vitest, 45 tests)
cd frontend && npm run test

# Servidor MCP (pytest, 47 tests, backend falso)
cd mcp-server && .venv/bin/python -m pytest -q
```

## Responsive / Mobile
- Todos los grids usan `grid-cols-1 sm:grid-cols-2` como base
- Tablas wrapped en `overflow-x-auto`
- Filtros usan `flex-wrap` para mobile
- Dialog forms son responsive con breakpoints sm/lg

## UI/UX
- Skill UI/UX Pro Max instalado en `.claude/skills/ui-ux-pro-max/`
- Focus states: ring amarillo `#FFD600` con `focus-visible`
- Transiciones: 150ms en elementos interactivos
- `prefers-reduced-motion` respetado
- Card hover: borde sutil + sombra brand
- Font mono: JetBrains Mono para datos numéricos (clase `.mono`)

## Errores conocidos
- **Añadir un valor a un `enum.Enum` no basta.** El tipo enum de Postgres ya
  existe en producción y `_ensure_pg_enums` solo crea tipos *ausentes*, así que
  el valor nuevo no llega y el primer INSERT revienta (le pasó a `vattreatment`,
  parcheado a mano). Ahora `_ensure_enum_values()` emite `ALTER TYPE ... ADD
  VALUE IF NOT EXISTS` para todos los enums del ORM; se llama desde el lifespan
  de `main.py`, **no** desde `run_migrations()` (que solo usa `init_db`).
  El test `tests/integration/test_advanced_status_integration.py` guarda el
  invariante contra Postgres real.
- **Al añadir un estado a `TaskStatus`**, revisar los listados explícitos de
  estados: usa `ACTIVE_TASK_STATUSES` / `IN_PROGRESS_TASK_STATUSES` de
  `models.py` en vez de escribir la lista a mano. Los sitios que filtran por
  `!= completed` no necesitan cambios; los que enumeran, sí, o el estado nuevo
  desaparece de dashboards, capacidad, digests e informes sin avisar.
- **`lazy="selectin"` está en CASI TODAS las relaciones de `models.py`.** Quitar un
  `selectinload()` de `.options()` NO evita la carga: el modelo la fuerza igual. Para
  que un listado no arrastre colecciones hay que desactivarlas con `noload(...)`
  explícito en la query. Verificarlo contra Postgres real (`tests/integration/`), no
  con la suite unitaria: ahí `get_db` está mockeado y el SQL no se ejecuta.
- Los estados de rentabilidad se deciden en `services/profitability.py`, un único
  sitio. Si añades un valor al enum, añádelo también a `frontend/src/lib/profitability.ts`
  (el test `profitability.test.ts` falla si te lo saltas).
- **Los timeouts de las llamadas a Claude se dimensionan por tokens de SALIDA.**
  El parseo de un daily de 12 proyectos tarda ~20 s (2.000 tokens generados); uno
  de 3 proyectos, 7 s. Un `with_options(timeout=...)` por debajo de eso corta la
  generación a media respuesta y el reintento sólo repite el corte. Presupuesto
  actual: `timeout=40, max_retries=1` (80 s) dentro de los 90 s que `dailysApi`
  da a `submit`/`reparse`/`edit`. Lo guarda `TestDailyParserBudget` en
  `tests/test_dailys.py`. Los demás endpoints de IA ya usaban 90 s en
  `frontend/src/lib/api.ts`; los de dailys iban con los 30 s por defecto.
- **Un fallo de IA que se guarda como estado tiene consumidores.** `POST /api/dailys`
  guarda la fila antes de parsear (bien: no se pierde el texto), pero deja
  `parsed_data = NULL` si Claude falla. `POST /dailys/{id}/send-discord` rechazaba
  ese daily con un 400 y el informe del día no salía; ahora publica el texto en
  crudo con `format_raw_daily_embed()` y avisa en el mensaje de vuelta. Al tocar
  el parseo, mirar siempre quién lee después ese campo.
- **Una tabla o columna NUEVA va en una migración versionada**, no en el lifespan
  ni en `create_all` (que sólo corre en `init_db`, nunca en producción). Patrón:
  contrato JSON en `backend/startup/schema_versions/<x>_v1.json` + módulo
  `backend/startup/<x>_schema.py` con `apply`/`verify` + añadirlo al final de
  `MIGRATIONS` en `deployment_schema.py`. Railway ejecuta
  `python -m backend.scripts.migrate` en el release y el arranque se niega a
  servir si falta una versión. Ejemplo reciente: `gsc_schema.py`. Las versiones
  ya publicadas son inmutables (su checksum se comprueba).
- **Borrar una tabla o columna publicada no es un `DROP` suelto.** P12 se
  verifica en cada arranque y exige todas sus tablas y columnas. Los pasos de
  retirada usan `startup/retirement_schema.py` (`Retirement("<x>_v1.json")`,
  contrato con `drop_tables`/`drop_columns`) y `schema_baseline` sólo perdona lo
  de su tupla `RETIREMENTS` cuando ya no existe. Para retirar algo más: contrato
  + módulo de 5 líneas (ver `report_policy_legacy_retirement_schema.py`),
  añadirlo a `RETIREMENTS` y al final de `MIGRATIONS`, quitar la columna del ORM
  y de `readiness.py`, y probar subida con datos e instalación limpia
  (`test_report_policy_legacy_retirement_schema.py`). Ojo: el `DROP` corre en el
  pre-deploy, con el contenedor viejo aún sirviendo; si el ORM viejo mapea la
  columna, sus consultas a esa tabla fallan hasta el relevo.
- **`parse_claude_json` no puede exigir que la respuesta empiece por el JSON.** Con
  notas vacías el parser de dailys recibía una frase inventada antes del bloque
  ```json y respondía 502 en cada reintento (daily 129 de Nacho, oct 2026). Ahora
  se extrae el primer objeto del texto, y con notas vacías el prompt lo dice y se
  descartan las tareas sin `fact_keys`. Lo guarda `TestDailySoloConHechos`.
- bcrypt pinned a 4.1.3 (incompatibilidad passlib)

---

*Actualizado: 22 Oct 2026*
