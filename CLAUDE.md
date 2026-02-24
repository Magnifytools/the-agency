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
- Users: `david@magnify.ing` / `Magnify2026!` (admin), `nacho@magnify.ing` / `Magnify2026!` (member)
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
reports, growth, communications,
finance_income, finance_expenses, finance_taxes, finance_forecasts,
finance_advisor, finance_import, finance_dashboard,
admin_users, admin_settings
```

## Environment Variables (.env)
- `DATABASE_URL` - PostgreSQL connection (default: postgresql+asyncpg://agency:agency@localhost:5432/the_agency)
- `SECRET_KEY` - JWT signing key
- `ACCESS_TOKEN_EXPIRE_MINUTES` - Token TTL (default: 480)
- `DISCORD_WEBHOOK_URL` - Optional Discord webhook

## No tocar
- Módulos financieros custom: tax_service, forecast_service, income, expenses, taxes, forecasts
- Se reemplazarán por integración Holded en fase posterior
- Si necesitas importar algo de estos módulos, no lo hagas. Trabaja alrededor.

## Errores conocidos
- bcrypt pinned a 4.1.3 (incompatibilidad passlib)
- `Base.metadata.create_all` no agrega columnas a tablas existentes. Para nuevas columnas en tablas existentes, agregar `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` en `backend/main.py` lifespan.

---

*Actualizado: 24 Feb 2026*
