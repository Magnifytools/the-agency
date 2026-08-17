# Findings — Exploración código

## Modelo de tiempo (3 métricas confirmadas)

`client-detail-page.tsx:343-356` muestra 3 cards:
- **Tiempo estimado** = `summary.total_estimated_minutes` → fuente `tasks.estimated_minutes` (estimación manual al crear tarea)
- **Tiempo real** = `summary.total_actual_minutes` → fuente `tasks.actual_minutes` (declaración al cerrar tarea)
- **Tiempo tracked** = `summary.total_tracked_minutes` → fuente `time_entries.minutes` agregado (timer real)

Página de proyecto `/projects/:id` (`projects.py:558-566`) usa **solo TimeEntry.minutes** filtrado por `Task.project_id == project_id`. Por eso 27,77h en Fit Generation: las 169 tareas huérfanas (project_id NULL) tienen time entries que no se cuentan en la vista de proyecto pero sí se cuentan agregadas a nivel cliente.

**Conclusión clave**: F2 (backfill) **arregla F5 y F6 automáticamente** sin tocar código. Una vez vinculadas las tareas al proyecto, las cifras coincidirán.

## F1 — Quick Task Modal

- **Archivo**: `frontend/src/components/timer/active-timer-bar.tsx:38-41,227-246,154-156`
- Estado actual: `qcTitle`, `qcClientId`. Falta `qcProjectId`.
- API call no pasa `project_id`.
- Backend schema `TaskCreate` ya acepta `project_id: Optional[int]` → no requiere cambio backend.
- **Cambio**: añadir state, select condicional, query proyectos del cliente, pasarlo en la mutación.

## F2 — Backfill

- `tasks.project_id` es `nullable=True`
- `Client.projects` relación disponible
- Script `backend/scripts/backfill_task_projects.py` nuevo
- Lógica: para cada tarea con project_id NULL, si el cliente tiene exactamente 1 proyecto activo → setear

## F3 — Filtro Sin proyecto

- **Frontend**: `frontend/src/pages/tasks-page.tsx:513-551` (chips existentes), `:83-86` (state `qaFilter`)
- **Backend**: `backend/api/routes/tasks.py:100-229` — añadir param `no_project: bool`

## F4-F6 — Tiempo

- `client-dashboard-tab.tsx` usa TimeEntry.minutes (correcto)
- `projects.py:558-566` también usa TimeEntry.minutes (correcto)
- Las 3 métricas en `client-detail-page.tsx:343-356` son conceptualmente distintas, no duplicadas
- **F5**: renombrar "Horas consumidas" del proyecto a "Tiempo tracked" + tooltip explicativo. Cambio cosmético.
- **F4**: en la ficha del cliente, hacer Tracked la métrica principal grande, Estimated/Real como info secundaria (collapsible o tooltip)
- **F6**: tras F2, cifras coinciden automáticamente

## F7 — 14 pestañas cliente

- `client-detail-page.tsx:226`: `validTabs = ["ficha","actividad","tareas","proyectos","comunicaciones","contactos","panel","tiempo","facturacion","recursos","seo","informes","ajustes","facturas"]`
- Tabs gated: `seo` (si engine_project_id), `facturas` (si admin + holded configured)
- Propuesta agrupación:
  - **Ficha** (sin cambio)
  - **Actividad** (sin cambio)
  - **Tareas** (sin cambio)
  - **Proyectos** (sin cambio)
  - **Panel** (sin cambio)
  - **Tiempo y Dinero** (= Tiempo + Facturación + Facturas en subtabs internos)
  - **Outputs** (= SEO + Informes en subtabs internos)
  - **Comunicación** (= Contactos + Comunicaciones en subtabs internos)
  - **Recursos** (sin cambio)
  - **Ajustes** (sin cambio)
- Resultado: 10 pestañas top-level → más reducible si junto Ficha+Actividad

## F8 — Burndown

- `project-detail-page.tsx:91-95,329-356` — usa recharts `LineChart`
- Project model tiene `is_recurring: Boolean`
- Wrappear con `{!project.is_recurring && <Burndown />}`
- Para recurring: nuevo componente "MonthlyLoadChart" (carga mensual vs monthly_fee/budget_hours)

## F9 — Timesheet dropdown

- `frontend/src/pages/timesheet-page.tsx:204-211,260-262`
- Bug: el dropdown se construye a partir de tasks **filtradas por `assigned_to: user.id`**
- Fix: cargar clientes activos directamente desde `clientsApi.list()` en lugar de derivar de tasks

## F10-F12 — Cosmético

- F10: badge "(N activas)" en el contador "17 tareas" → añadir en tasks-page header
- F11: añadir label "(del mes seleccionado)" al título "Rentabilidad por cliente"
- F12: tooltip en columna EST/REAL de tasks-page

## Orden propuesto de ejecución

1. F1 (modal proyecto) — beneficio mayor, riesgo bajo
2. F2 (backfill) — depende de saber que F1 está en producción para no recrear el problema
3. F9 (timesheet dropdown) — quick win
4. F3 (filtro sin proyecto) — para detección
5. F5 (renaming + tooltip Horas consumidas)
6. F4 (jerarquía 3 métricas)
7. F8 (burndown vs recurring)
8. F11 (label dashboard)
9. F12 (tooltip EST/REAL)
10. F10 (badge activas)
11. F7 (agrupar pestañas) — el más invasivo, último
12. F6 (verificación cifras coinciden)
