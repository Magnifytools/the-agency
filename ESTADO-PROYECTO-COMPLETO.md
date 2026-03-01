# The Agency — Estado Completo del Proyecto

> Generado: 2026-03-01 | Owner: David | 60 commits | Deploy: Railway (auto desde main)
> URL prod: https://agency.magnifytools.com

---

## 1. Qué es

Plataforma interna para gestionar una agencia de marketing digital (Magnify). Cubre:
- Gestión operativa (clientes, proyectos, tareas, timesheet)
- Pipeline de ventas (leads, propuestas con IA)
- Finanzas (ingresos, gastos, impuestos, previsiones, asesor IA)
- Comunicaciones (log, email drafting IA, Discord, digests semanales IA)
- Daily updates con parseo IA
- Dashboard con métricas, rentabilidad, cierre mensual
- Growth tracking (ideas ICE)

---

## 2. Tech Stack

| Capa | Tecnología |
|------|-----------|
| **Backend** | FastAPI + async SQLAlchemy 2.0 + asyncpg |
| **DB** | PostgreSQL 16 |
| **Frontend** | React 19 + TypeScript + Vite + Tailwind CSS v4 |
| **State** | TanStack Query v5 (server) + React Context (auth) |
| **UI** | Componentes shadcn-style (CVA + tailwind-merge) |
| **IA** | Anthropic Claude API (`claude-sonnet-4-20250514`) via `anthropic==0.49.0` |
| **Auth** | JWT (HS256) + bcrypt, role-based + module permissions |
| **Deploy** | Railway (auto-deploy desde GitHub main) |
| **Integración** | Holded ERP (opcional), Discord webhooks |

**Puertos dev:** Frontend 5177, Backend 8004

---

## 3. Estructura del Proyecto

```
the-agency/
├── backend/
│   ├── main.py                    # App FastAPI, CORS, lifespan, 37 routers
│   ├── config.py                  # Settings desde .env (Pydantic)
│   ├── api/
│   │   ├── deps.py                # get_current_user, require_admin, require_module
│   │   └── routes/                # 29 archivos de rutas
│   ├── core/security.py           # JWT + bcrypt
│   ├── db/
│   │   ├── database.py            # Async engine + session
│   │   ├── models.py              # 38 modelos SQLAlchemy
│   │   └── seed.py                # Seed inicial
│   ├── schemas/                   # 30 módulos Pydantic
│   └── services/                  # 14 servicios de lógica
├── frontend/
│   ├── src/
│   │   ├── App.tsx                # Router (29 rutas)
│   │   ├── context/auth-context   # AuthProvider
│   │   ├── lib/api.ts             # Axios + typed APIs (26KB)
│   │   ├── lib/types.ts           # Interfaces TS (27KB)
│   │   ├── components/            # 28 componentes
│   │   └── pages/                 # 29 páginas
│   ├── vite.config.ts             # Proxy /api → :8004
│   └── package.json
├── docker-compose.yml             # PostgreSQL
├── Dockerfile                     # Para Railway
└── .env                           # Variables de entorno
```

---

## 4. Modelos de Base de Datos (38 modelos)

### Core
- **User** — email, full_name, role (admin/member), hourly_rate, permissions
- **Client** — name, email, company, contract_type (monthly/project/retainer), monthly_budget, status (active/paused/finished), holded_contact_id
- **Project** — name, client_id, status (planning/active/on_hold/completed/cancelled), budget_hours, budget_amount
- **ProjectPhase** — project_id, name, order_index, phase_type (sprint/milestone/standard)
- **Task** — title, client_id, project_id, category_id, assigned_to, status (pending/in_progress/completed), priority (urgent/high/medium/low), estimated_minutes, due_date, is_inbox
- **TaskCategory** — name, default_minutes (8 categorías SEO pre-seed)
- **TimeEntry** — user_id, task_id, minutes, started_at, date, notes

### Ventas
- **Lead** — company_name, contact_name, email, status (new/contacted/discovery/proposal/negotiation/won/lost), source, estimated_value, assigned_to
- **LeadActivity** — lead_id, activity_type, description
- **Proposal** — lead_id, client_id, title, service_type, situation, problem, pricing_options (JSON), status (draft/sent/accepted/rejected/expired), converted_project_id
- **ServiceTemplate** — service_type (enum), default_phases, price_range, prompt_context

### Comunicaciones
- **CommunicationLog** — client_id, channel (email/call/meeting/whatsapp/slack/other), direction (inbound/outbound), subject, summary, requires_followup, followup_date
- **WeeklyDigest** — period_start/end, status (draft/reviewed/sent), tone, content (JSON generado por IA)
- **DailyUpdate** — user_id, date, raw_text, parsed_data (JSON parseado por IA), status (draft/sent)

### Finanzas
- **Income** — date, description, amount, client_id, type (factura/recurrente/extra), vat_rate, status
- **Expense** — date, description, amount, category_id, is_recurring, vat_rate, is_deductible
- **ExpenseCategory** — name, color (8 pre-seed)
- **Tax** — name, model (303/200/111/115), period, year, base_amount, tax_rate, status
- **Forecast** — month, projected_income/expenses/taxes/profit, confidence
- **FinancialSettings** — tax_reserve, credit_limit, monthly_close_day, vat_rate
- **MonthlyClose** — year, month, 7 checkboxes de revisión, responsible_name

### PM & Insights
- **PMInsight** — insight_type (deadline/stalled/overdue/followup/workload/suggestion/quality), priority, status
- **Event** — title, event_type, start_time, end_time
- **AlertSettings** — user_id, umbrales de notificación

### Finanzas IA
- **FinancialInsight** — type (alerta/consejo/anomalia), severity
- **AdvisorTask** — source_key, title, priority, due_date
- **AdvisorAiBrief** — AI brief storage

### Integración Holded
- **HoldedSyncLog**, **HoldedInvoiceCache**, **HoldedExpenseCache**

### Otros
- **Invoice**, **InvoiceItem** — Legacy billing
- **AuditLog** — action, entity_type, entity_id
- **UserPermission** — user_id, module, can_read, can_write
- **UserInvitation** — email, token, expires_at
- **GrowthIdea** — title, funnel_stage, status, ICE score
- **GeneratedReport** — report_type, title, period, content
- **DiscordSettings** — webhook_url, auto_daily_summary, summary_time
- **SyncLog**, **CsvMapping** — CSV import

---

## 5. Endpoints API (29 archivos de rutas)

### Auth & Usuarios
- `POST /api/auth/login` — Login con email/password, devuelve JWT
- `GET /api/auth/me` — Usuario actual
- CRUD usuarios (admin only)
- Invitaciones con token + permisos por módulo

### Clientes
- CRUD `/api/clients` — Con soft delete (status=finished)
- `GET /api/clients/{id}/summary` — Resumen con proyectos, tareas, horas

### Proyectos
- CRUD `/api/projects` — Con fases, desde templates
- Phases: CRUD anidado

### Tareas
- CRUD `/api/tasks` — Con filtros: client_id, project_id, status, category_id, assigned_to

### Time Tracking
- CRUD `/api/time-entries`
- `POST /api/timer/start` — Iniciar timer
- `POST /api/timer/stop` — Parar timer (cap 8h)
- `GET /api/timer/active` — Timer activo del usuario
- `GET /api/admin/timers/active` — Todos los timers activos (admin)
- `GET /api/time-entries/export` — Export CSV con filtros
- `GET /api/time-entries/by-project` — Reporting agrupado por proyecto

### Pipeline de Ventas
- CRUD `/api/leads` + actividades + `POST /api/leads/{id}/convert`
- CRUD `/api/proposals` + duplicate, status update, convert, PDF, **IA generation**

### Comunicaciones
- CRUD `/api/clients/{id}/communications`
- `POST /api/communications/draft-email` — **Redacción email con IA**
- `GET /api/communications/pending-followups`

### Daily Updates (NUEVO)
- `POST /api/dailys` — Submit daily, **parseo con IA** a proyectos/tareas
- `GET /api/dailys` — Listar con filtros date_from, date_to, user_id
- `GET /api/dailys/{id}` — Detalle
- `POST /api/dailys/{id}/reparse` — **Re-parsear con IA**
- `POST /api/dailys/{id}/send-discord` — Enviar a Discord
- `DELETE /api/dailys/{id}`

### Digests Semanales
- `POST /api/digests/generate` — **Generar con IA** (collector + generator)
- CRUD + render en Slack/Email/Discord

### Discord
- Settings (webhook URL, auto-summary)
- Test webhook
- `POST /api/discord/send-daily-summary` — Resumen horas del día
- `POST /api/discord/send-digest/{id}` — Enviar digest

### Reports
- CRUD `/api/reports`
- `POST /api/reports/{id}/ai-narrative` — **Narrativa IA** para reports

### Dashboard
- Overview, profitability, team stats
- Monthly close (checklist), financial settings

### Finanzas
- CRUD income, expenses, expense categories
- Taxes: CRUD + calendar + summary + calculate
- Forecasts: CRUD + generate + runway + vs-actual
- Advisor: insights, tasks, **AI briefs**, monthly close

### Growth
- CRUD ideas con ICE scoring

### Integración Holded
- Sync contactos, facturas, gastos desde Holded ERP
- Dashboard financiero unificado

### Import/Export
- CSV import con preview + mappings
- Export income/expenses/taxes

---

## 6. Features de IA (4 integraciones con Claude API)

Todas usan `anthropic==0.49.0` con modelo `claude-sonnet-4-20250514`.

### 6.1 Daily Updates Parser (`backend/services/daily_parser.py`)
- Input: texto libre del daily de un miembro del equipo
- Output: JSON estructurado con proyectos, tareas por proyecto, tareas generales, plan para mañana
- Se usa en `POST /api/dailys` y `POST /api/dailys/{id}/reparse`

### 6.2 Digest Generator (`backend/services/digest_generator.py`)
- Input: datos recopilados de la semana (tareas, time entries, comunicaciones)
- Output: digest con greeting, secciones (done, need, next), closing
- 3 tonos: formal, cercano, equipo
- Se usa en `POST /api/digests/generate`

### 6.3 Email Drafter (`backend/services/email_drafter.py`)
- Input: nombre cliente, contacto, propósito, comunicación previa (reply), contexto reciente
- Output: JSON con subject, body, tone, suggested_followup
- Se usa en `POST /api/communications/draft-email`

### 6.4 Report Narrator (`backend/services/report_narrator.py`)
- Input: datos del report (métricas, período)
- Output: narrativa profesional del informe
- Se usa en `POST /api/reports/{id}/ai-narrative`

### 6.5 Client Advisor (`backend/services/client_advisor.py`)
- Input: datos operativos y financieros del cliente
- Output: recomendaciones IA contextualizadas
- Se usa en `GET /api/clients/{id}/dashboard`

### Infraestructura IA Compartida (`backend/services/ai_utils.py`)
- Singleton `get_anthropic_client()`: reutiliza conexión TCP/SSL entre llamadas
- `parse_claude_json()`: parseo robusto de respuestas Claude (maneja markdown code blocks)
- Rate limiter con sliding window (Redis + fallback in-memory)

---

## 7. Páginas Frontend (29 rutas)

| Ruta | Página | Descripción |
|------|--------|-------------|
| `/login` | LoginPage | Email + password |
| `/dashboard` | DashboardPage | Métricas, rentabilidad, inbox, cierre mensual |
| `/clients` | ClientsPage | Tabla con tabs por status, CRUD |
| `/clients/:id` | ClientDetailPage | Detalle con proyectos, tareas, comunicaciones, horas |
| `/leads` | LeadsPage | Pipeline kanban/tabla, CRUD, actividades |
| `/leads/:id` | LeadDetailPage | Detalle lead con actividades |
| `/projects` | ProjectsPage | Lista proyectos, CRUD |
| `/projects/:id` | ProjectDetailPage | Fases, tareas, presupuesto |
| `/tasks` | TasksPage | Kanban + tabla, filtros, CRUD |
| `/growth` | GrowthPage | Ideas ICE, filtros |
| `/timesheet` | TimesheetPage | Registro horas, timer, resumen |
| `/dailys` | DailysPage | Submit daily → parseo IA, histórico, re-parse, Discord |
| `/digests` | DigestsPage | Generar digest IA, listar, enviar |
| `/digests/:id/edit` | DigestEditPage | Editar digest |
| `/reports` | ReportsPage | Generar reports, narrativa IA |
| `/proposals` | ProposalsPage | CRUD propuestas, IA, PDF |
| `/billing` | BillingPage | Facturación |
| `/finance` | FinanceDashboardPage | Dashboard financiero |
| `/finance/income` | IncomePage | CRUD ingresos |
| `/finance/expenses` | ExpensesPage | CRUD gastos |
| `/finance/taxes` | TaxesPage | Impuestos, calendario, resumen |
| `/finance/forecasts` | ForecastsPage | Previsiones, runway |
| `/finance/advisor` | AdvisorPage | Asesor financiero IA |
| `/finance/import` | ImportPage | Import CSV |
| `/finance-holded` | HoldedFinancePage | Finanzas via Holded ERP |
| `/users` | UsersPage | Gestión equipo (admin) |
| `/discord` | DiscordSettingsPage | Config webhook Discord (admin) |

---

## 8. Permisos y Auth

### Roles
- **admin**: acceso total, bypass de permisos
- **member**: acceso según permisos por módulo

### Módulos de permisos
`dashboard, clients, projects, tasks, timesheet, billing, proposals, reports, growth, communications, digests, leads, finance_dashboard, finance_income, finance_expenses, finance_taxes, finance_forecasts, finance_advisor, finance_import, admin_users, admin_settings`

### Patrón backend
- `Depends(get_current_user)` — cualquier usuario autenticado
- `Depends(require_admin)` — solo admin
- `Depends(require_module("nombre"))` — usuario con permiso en ese módulo
- `Depends(require_module("nombre", write=True))` — con permiso de escritura

### Patrón frontend
- `hasPermission(module)` filtra nav items
- Items sin `module` se muestran a todos (ej: dailys)
- `isAdmin` controla sección admin del sidebar

---

## 9. Usuarios Seed

| Email | Password | Rol |
|-------|----------|-----|
| david@magnify.ing | Magnify2026! | admin |
| nacho@magnify.ing | Magnify2026! | member |

---

## 10. Mensajes Discord (3 tipos)

1. **Resumen diario de horas** — Agrupado por persona → cliente → tareas con duración
2. **Daily update individual** — Daily parseado por IA, formateado con emojis y markdown
3. **Digest semanal** — Resumen de la semana generado por IA

Todos usan el mismo webhook configurado en Admin > Discord.

---

## 11. Dependencias

### Backend (requirements.txt)
fastapi 0.115.6, uvicorn 0.34.0, sqlalchemy 2.0.36, asyncpg 0.30.0, pydantic-settings 2.7.1, python-jose 3.3.0, bcrypt 4.1.3, alembic 1.14.1, httpx 0.28.1, anthropic 0.49.0, jinja2 3.1.4, python-dateutil, aiofiles, email-validator, python-multipart, eval-type-backport

### Frontend (package.json)
react 19.2, react-dom, react-router-dom 7.13, @tanstack/react-query 5.90, axios, tailwindcss 4.1, recharts 3.7, date-fns 4.1, lucide-react, sonner, zod 4.3, react-hook-form 7.71, @dnd-kit (core + sortable), class-variance-authority, clsx, tailwind-merge

---

## 12. Git History Reciente (últimos 20)

```
800d177 fix: add missing Engine integration columns on startup
dd7d5f6 feat: add admin active timers, CSV export, and project reporting to timesheet
fd17b51 fix: time tracking bugs + update project docs and sprint roadmap
e6e4a60 refactor: code quality, reuse and efficiency improvements
a17615f fix: add logging.basicConfig so lifespan logs appear in production
46c46e8 feat: add periodic Engine metrics sync with local cache
4667751 feat: add Engine SEO metrics widget to client detail
2100c88 Add Engine integration: proxy endpoints, model fields, and config
44d1d55 fix: add HSTS and security headers to resolve Chrome "Not Secure" warning
feae3fb fix: default AUTH_COOKIE_SECURE to true in production
d797f13 feat: typography upgrade + audit post-fixes + API bug fixes
3d05b96 Audit remediation: implement all 13 findings (C/H/M)
60fd334 fix: notification system - fix broken imports, add service layer, integrate triggers
f4cb3f9 feat: Gantt view, project Kanban, notifications, exec dashboard, dashboard refactor, tests
5bb0397 Audit remediation: security, performance, and permission fixes
eb9cd04 Add client activity timeline and improve task board views
654aa6c CRM features: client contacts, health scoring, capacity planning
e1c087e Tech debt: async AI services, code splitting, rate limiting, permission scoping
abedb59 Audit remediation: SECRET_KEY guard, billing export auth, Discord contract, user privacy
8375a50 Fix audit bugs: ownership checks, date validation, UI fixes for dailys
47d1ff5 Add AI features: Daily Updates, Report Narratives, Email Drafting
bc218aa Audit remediation Fases 1-3: seed security, DDL hardening, error boundaries
85b4b2d Security hardening and error handling fixes (Audit Fase 0)
```

---

## 13. Estado Actual y Pendientes

### Completado
- CRUD completo de todas las entidades (38 modelos)
- Auth JWT con roles y permisos por módulo
- Dashboard ejecutivo con métricas, rentabilidad, inbox
- Pipeline ventas (leads → propuestas → clientes)
- Time tracking con timer en tiempo real + resumen semanal + admin timers + CSV export + reporting por proyecto
- Comunicaciones con log, followups y email drafting IA
- 5 integraciones IA (dailys, digests, email, reports, client advisor)
- Infraestructura IA compartida (singleton client, JSON parser, rate limiter)
- Discord webhooks (3 tipos de mensaje)
- Finanzas completas (income, expenses, taxes, forecasts, advisor)
- Integración Holded ERP (sync contactos, facturas, gastos)
- Integración Engine (métricas SEO por cliente, sync periódico)
- Import CSV + Export (PDF, CSV)
- CRM: contactos de cliente, health scoring, capacity planning
- Gantt view, project Kanban, activity timeline
- Sistema de notificaciones con triggers
- Auditoría de seguridad completada (4 fases) + HSTS + secure cookies
- Tests: 22 backend + 30 frontend
- Deploy en Railway funcionando (auto-deploy desde main)

### Tech Debt Conocido
- ~~Anthropic client síncrono~~ **Resuelto** — ahora usa `AsyncAnthropic` singleton en `ai_utils.py`
- ~~Sin rate limiting en IA~~ **Resuelto** — sliding window limiter (Redis + fallback in-memory)
- ~~Lógica markdown duplicada~~ **Resuelto** — `parse_claude_json()` centralizado
- ~~N+1 queries en dashboard~~ **Resuelto** — usa `scalar_subquery()`
- **bcrypt 4.1.3 pinned** por incompatibilidad passlib (warning cosmético)
- **Sin Alembic migrations** — DDL en lifespan, funcional pero no ideal para producción
- **Módulos financieros custom** (income, expenses, taxes, forecasts) serán reemplazados por Holded
### Pendiente (Sprint 6-9)
- **Sprint 6**: PM Intelligence (insights IA proactivos + daily briefing)
- **Sprint 7**: Propuestas SCQA avanzadas + modelos de inversión SEO
- **Sprint 8**: Reporting SCQA + export PDF profesional
- **Sprint 9**: Biblioteca de evidencia + mejoras UX generales

---

## 14. Cómo Correr en Local

```bash
# 1. PostgreSQL
docker compose up -d

# 2. Backend
cd backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # Configurar DATABASE_URL, SECRET_KEY, ANTHROPIC_API_KEY
python -m backend.db.seed
uvicorn backend.main:app --reload --port 8004

# 3. Frontend
cd frontend
npm install
npm run dev  # http://localhost:5177
```

**Variables de entorno necesarias:**
- `DATABASE_URL` — PostgreSQL connection string
- `SECRET_KEY` — JWT signing key
- `ANTHROPIC_API_KEY` — Para features de IA (opcional sin IA)
- `DISCORD_WEBHOOK_URL` — Para Discord (opcional)
- `HOLDED_API_KEY` — Para Holded ERP (opcional)
