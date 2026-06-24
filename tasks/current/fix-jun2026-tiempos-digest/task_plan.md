# Fix Jun 2026 — Alerta tiempos por proyecto + Digest cierre Slack

## Bug 2 — Digest: el cierre desaparece en Slack (Fit Generation)
- Causa raíz: `_render_slack_custom` en `backend/services/digest_renderer.py` tiene un
  opt-out `template.get("show_closing", True)`. La plantilla de Fit Generation lo tiene
  desactivado, así que el cierre se omite SOLO en Slack-custom (email/Discord/Slack-default
  siempre lo muestran).
- Fix: eliminar el opt-out → el cierre se incluye siempre que exista, como el resto de canales.

## Bug 1 — Alerta de tiempos por proyecto no visible
Decisiones del usuario:
- Extensión muestra: **presupuesto SEMANAL del proyecto** de la tarea activa (quedan Xh + alerta).
- Alerta visible en: **extensión (popup)** + **página de proyecto**.
- Ventana: **semanal informativo + visual; el techo MENSUAL sigue disparando la notificación dura**.

### Backend
1. `services/time_budget.py` (nuevo): `build_budget_status(weekly_budget, monthly_budget, week_minutes, month_minutes)` — función pura con umbrales (ok <0.8, warning >=0.8, over >=1.0).
2. `time_entries.py`: `_TIME_ENTRY_RESPONSE_OPTIONS` carga `Task.project`; `ActiveTimerResponse` + project_id/project_name; poblar en active/start/pause/resume.
3. `GET /api/timer/project-budget/{project_id}` (gated `timesheet`): estado semanal+mensual del proyecto (agregado a nivel proyecto, como notifications.py).
4. `projects.py get_project`: añadir `hours_used_week` / `hours_used_month`.
5. `schemas/project.py`: añadir esos 2 campos a `ProjectResponse`.

### Frontend (web)
6. `lib/types.ts`: Project += hours_used_week, hours_used_month.
7. `project-detail-page.tsx`: banner de estado semanal (guía) + mensual (alerta) por colores.

### Extensión
8. `popup.html` + `popup.css`: panel de presupuesto.
9. `popup.js`: al cargar timer activo con project_id → fetch budget → render "quedan Xh esta semana" + alerta.

## Verificación
- pytest backend (digest renderer + nuevo endpoint).
- tsc frontend.
- Smoke manual del endpoint si hay DB.
