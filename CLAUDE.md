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
- Client DELETE is soft delete (status=finished)
- Eager loading (`lazy="selectin"`) for denormalized responses
- TanStack Query for server state, React Context for auth
- Path alias: `@/` -> `src/`

## Permission Modules
```
dashboard, clients, projects, tasks, timesheet, billing, proposals,
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

## Buffer de Ideas (Growth)
- **Concepto**: Backlog de ideas **por proyecto**, priorizadas con ICE (Impact/Confidence/Ease)
- **Flujo**: Idea → Puntuar ICE → Convertir a Tarea o Proyecto
- **Backend**: tabla `growth_ideas` con `project_id` FK, rutas en `/api/growth`, módulo `growth`
- **Frontend**: página `/growth` (Buffer global con filtro por proyecto) + tab "Buffer" en detalle de proyecto
- **Nomenclatura**: UI dice "Buffer de Ideas" / "Buffer", código interno sigue usando `growth` (evita migración DB)
- **No confundir** con Pipeline/Leads (`/leads`) que es el CRM comercial

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
# Backend (pytest, 425 tests — incluye tests/integration contra Postgres real)
cd backend && source venv/bin/activate && python -m pytest tests/ -v

# Frontend (vitest, 45 tests)
cd frontend && npm run test
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
- **El lifespan de `main.py` NO ejecuta `create_all`** — sólo lo hace `init_db`,
  que en producción no corre. Una tabla NUEVA del ORM no aparece sola: hay que
  añadir su `CREATE TABLE IF NOT EXISTS` a la lista de DDL inline del lifespan,
  como `project_evidence` y `change_logs`. Y el índice va DESPUÉS del CREATE, o
  el arranque loguea `UndefinedTableError` y sigue sin índice.
- bcrypt pinned a 4.1.3 (incompatibilidad passlib)
- `Base.metadata.create_all` no agrega columnas a tablas existentes. Para nuevas columnas en tablas existentes, agregar `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` en `backend/main.py` lifespan.

---

*Actualizado: 27 Ago 2026*
