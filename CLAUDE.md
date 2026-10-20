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
reports, growth (Pipeline + Buffer), communications, digests,
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
  arriba en `/digests`): una fila por cliente externo activo con el estado de su
  resumen del mes anterior. Entregado = entrega externa confirmada
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
- **"Entregado" = evento de entrega externa** (`digest_external_delivery_events`,
  botón "Marcar como entregado al cliente" del editor): guarda quién y cuándo.
  `DigestStatus.sent` es una etiqueta histórica sin evidencia: no cuenta.
- **Incidencia `report_unsent`** (`services/incident_report_conditions.py`): desde
  el día 1, por cada cliente externo activo con política mensual habilitada cuyo
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
- El PDF SEO completo sigue en The Engine (`/p/{engine_project_id}/reports`):
  el editor enlaza ahí. Su `report-data` NO se usa: traga errores como ceros y
  no pondera la posición.

## Estado del cliente (cartera)

- **Qué es**: la antigua salud 0-100 se sustituyó (19 oct 2026) por un estado
  explicado: `act` (Actuar) · `watch` (Vigilar) · `ok` (Bien) · `no_data`, con
  la lista de motivos. Vive en `backend/services/client_status.py`; API
  `GET /api/clients/portfolio` y `GET /api/clients/{id}/status`. La lista de
  clientes abre en la vista Cartera (`?vista=listado` para la tabla clásica) y
  la ficha muestra la misma tarjeta.
- **Señales** (umbrales en el propio módulo): tráfico de Google 28 días
  (`gsc_daily` propio; si no hay propiedad, summary de Engine), resumen según
  `ClientReportPolicy` (toca / atrasado tras 5 días), tareas vencidas (≥ 3 =
  Actuar; las tareas en espera no cuentan), seguimientos con el cliente
  vencidos y consumo de la cuota del mes (sólo admin, ≥ 90 % / ≥ 110 %).
- **No lee comunicaciones** (decisión de David): no añadas esa señal.
- Cada señal se calcula sólo si quien mira puede leer su fuente; sin ninguna
  señal el estado es `no_data`, nunca un "Bien" inventado.
- **Listo para entregar** (`ready`, sólo en `/{id}/status`, no en la cartera;
  pide leer tareas y resúmenes): tareas completadas (la revisión, si el proyecto
  la exige, ya pasó: sólo el responsable cierra) desde el inicio del periodo que
  toca entregar (cadencia de la política, mensual si no hay) o desde el día tras
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
  verifica en cada arranque y exige todas sus tablas y columnas. El paso
  `startup/phase0_retirement_schema.py` borra las de los módulos eliminados y
  `schema_baseline` sólo perdona lo retirado cuando ya no existe. Para retirar
  algo más: paso nuevo con su contrato, ampliar ese perdón y probar subida con
  datos e instalación limpia (`test_phase0_retirement_schema.py`).
- **`parse_claude_json` no puede exigir que la respuesta empiece por el JSON.** Con
  notas vacías el parser de dailys recibía una frase inventada antes del bloque
  ```json y respondía 502 en cada reintento (daily 129 de Nacho, oct 2026). Ahora
  se extrae el primer objeto del texto, y con notas vacías el prompt lo dice y se
  descartan las tareas sin `fact_keys`. Lo guarda `TestDailySoloConHechos`.
- bcrypt pinned a 4.1.3 (incompatibilidad passlib)

---

*Actualizado: 20 Oct 2026*
