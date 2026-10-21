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
- **Datos**: Engine ya manda en `/summary` los clics/impresiones de 30 días y de
  los 30 anteriores (`clicks_previous_30d`, `impressions_previous_30d`), sumados en
  la ventana. Se guardan dentro de `clients.engine_summary_data`; NO hay columnas
  ni snapshots propios. Posición anterior no llega → no se compara.
- **Cálculo**: `backend/services/seo_traffic.py` (Python + gemelo SQL sobre JSONB).
  `ClientResponse` expone `seo_clicks_change_pct`, `seo_impressions_change_pct`,
  `seo_trend` (`up`/`stable`/`down`/`drop_alert`; ±5 % es estable).
- **Lista de clientes**: columna "Tráfico SEO"; ordenar va al servidor
  (`GET /api/clients?sort=seo_change_asc|seo_change_desc`) para que los que más
  caen salgan primero en todas las páginas, no sólo en la visible.
- **Incidencia**: `client_seo_traffic_drop` en el inbox de incidentes existente
  (`services/incident_client_conditions.py`). Salta si los clics caen
  ≥ `SEO_DROP_ALERT_PCT` (20) con ≥ `SEO_DROP_MIN_CLICKS` (100) en el periodo
  anterior; crítica a partir del doble del umbral. Destinatarios: admins y
  responsables de proyectos activos/planificados del cliente con lectura de
  `clients`. Clave `...:open`: se resuelve sola al recuperarse y un descarte se
  mantiene mientras dure la misma caída.

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
  clients/{id}/status, digests + external-delivery-events), revisa
  `mcp-server/agency_mcp/server.py`.
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
- **Dos trampas al leer el detalle**: (1) Google anonimiza las consultas poco
  frecuentes, así que la suma de consultas < total de `gsc_daily`; "sin
  clasificar" = total − suma de consultas. (2) Las impresiones por página NO
  suman el total de la propiedad (una búsqueda que enseña dos páginas cuenta en
  las dos): el total sale siempre de `gsc_daily`.
- **El detalle no va a la IA**: ni resúmenes, ni borradores, ni asesor, ni
  enlace del cliente, ni MCP. Lo vigila `test_el_detalle_de_search_console_no_llega_a_la_ia`
  (`tests/test_gsc_detail.py`). Si lo cambias, cambia antes la política.
- El PDF SEO completo sigue en The Engine (`/p/{engine_project_id}/reports`):
  el editor enlaza ahí. Su `report-data` NO se usa: traga errores como ceros y
  no pondera la posición.

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
- **Fuera de la IA y del MCP a propósito** (política de privacidad): lo vigila
  `test_el_detalle_de_search_console_no_llega_a_la_ia`, que también prohíbe
  `seo_control`/`client_seo` en cualquier camino de IA.

## Estado del cliente (cartera)

- **Qué es**: la antigua salud 0-100 se sustituyó (19 oct 2026) por un estado
  explicado: `act` (Actuar) · `watch` (Vigilar) · `ok` (Bien) · `no_data`, con
  la lista de motivos. Vive en `backend/services/client_status.py`; API
  `GET /api/clients/portfolio` y `GET /api/clients/{id}/status`. La lista de
  clientes abre en la vista Cartera (`?vista=listado` para la tabla clásica) y
  la ficha muestra la misma tarjeta.
- **Señales** (umbrales en el propio módulo): tráfico de Google 28 días
  (`gsc_daily` propio; si no hay propiedad, summary de Engine), una señal por
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
  Console (totales y 120 días de detalle por consulta y página), GA4 y Calendar, que nada de eso va a la IA, que desconectar borra el
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

# Servidor MCP (pytest, 33 tests, backend falso)
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

*Actualizado: 20 Oct 2026*
