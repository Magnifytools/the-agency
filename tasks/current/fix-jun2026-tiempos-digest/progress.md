# Progreso

## Bug 2 — Digest cierre Slack ✅
- `digest_renderer.py::_render_slack_custom`: eliminado el opt-out `show_closing`.
  El cierre ahora se renderiza SIEMPRE que exista, igual que el resto de canales.
  → Esto arregla Fit Generation sin tocar la BD de producción (la plantilla tenía
    show_closing desactivado).
- Test nuevo: `tests/test_digest_renderer.py` (4 casos, incl. plantilla con show_closing=False).

## Bug 1 — Alerta tiempos por proyecto ✅
### Backend
- `services/time_budget.py` (nuevo) + test indirecto.
- `ActiveTimerResponse` += project_id/project_name; poblado en active/start/pause/resume.
  `_TIME_ENTRY_RESPONSE_OPTIONS` carga `Task.project`.
- `GET /api/timer/project-budget/{id}` (gated timesheet) — semana+mes vs presupuesto.
- `projects.py get_project` += hours_used_week / hours_used_month; schema actualizado.
- Test: `test_time_entries.py::TestProjectTimeBudget` (404 path).

### Frontend web
- `types/project.ts` += hours_used_week/month.
- `project-detail-page.tsx`: `HoursBudgetCard` (semana guía + mes alerta, colores).
- `npx tsc --noEmit` ✅

### Extensión
- `popup.html`: panel `#timer-budget` dentro del timer activo.
- `popup.css`: estilos budget (warning ámbar / over rojo).
- `popup.js`: `loadProjectBudget()` al iniciar timer activo; oculto en idle.
- `node --check popup.js` ✅

## Verificación
- pytest: digest (24) + projects (36) + time_entries OK.
- App completa importa OK.
- Pendiente: smoke visual E2E (requiere app + login + proyecto con presupuestos);
  los presupuestos por proyecto se configuran en la edición del proyecto.

## Iteración 2 — Techo efectivo (feedback David: "los proyectos ya tienen horas proyectadas") ✅
- Problema real: la alerta miraba `monthly_hours_budget` (normalmente vacío), pero los
  retainers rellenan `budget_hours` (form: "Presupuesto horas/mes"). Dos campos competían.
- `time_budget.effective_budgets(project)`: si no hay `monthly_hours_budget` y el proyecto es
  recurring / pricing monthly → usa `budget_hours` como techo mensual; deriva semanal (÷4.33) si falta.
- Aplicado en: notifications.py (query ampliada + bucle), endpoint extensión, projects.py
  (nuevos `effective_weekly/monthly_hours_budget` en la respuesta), banner web usa los efectivos.
- Tests: `test_time_budget.py` (6 casos). notifications/projects/time_entries siguen verdes.

## Iteración 3 — Aviso de cierre en proyectos puntuales (feedback David) ✅
Decisión: puntual = no techo mensual, pero tiene fecha final → avisar de cierre
(≤7 días / vencido) + horas vs tiempo restante (pace risk).
- `time_budget.build_closing_status()` + `is_recurring_project()`.
- `notifications.py`: bloque 9 — PROJECT_CLOSING_SOON / PROJECT_CLOSING_OVERDUE
  (solo no-recurrentes con target_end_date, status active).
- Endpoint extensión: `kind: recurring|fixed`; bloque `closing` para puntuales.
- `projects.py get_project`: `closing_status` en la respuesta.
- Frontend: `ProjectClosingCard` (fecha final, días, horas, aviso pace risk).
- Extensión: panel reutilizado en modo cierre ("Cierre: cierra en Xd" + "Horas").
- Tests: 7 nuevos en `test_time_budget.py`. Suite completa: 397 passed, 2 skipped.

## Iteración 4 — Fechas obligatorias al crear proyecto (feedback David) ✅
- `projects-page.tsx` diálogo "Nuevo proyecto":
  - Fecha inicio: **obligatoria** siempre (necesaria para el pace risk).
  - Fecha fin objetivo: **obligatoria en puntuales** (required={!is_recurring}); opcional en
    recurrentes (retainers sin cierre). `min` = fecha inicio (no permite fin < inicio).
  - Textos de ayuda según tipo.
- Validación nativa HTML5 (botón type=submit). tsc OK.
- Onboarding (clients-page) sigue siendo prefill IA (auto-crea); no es el "pedir al crear".

## Nota
- La alerta DURA (notificación campana) sigue siendo el techo MENSUAL — sin cambios.
  Lo semanal es guía visual en extensión + página de proyecto (acordado con David).
