# Progreso — 2026-05-23

## Estado: TODAS las 12 fixes aplicadas

## P0 — Sangrado ✅
- [x] **F1** Quick Task Modal con campo Proyecto + auto-preselección
  - `frontend/src/components/timer/active-timer-bar.tsx`: añadidos state `qcProjectId`, query proyectos activos del cliente, select condicional (oculto si no hay cliente; aviso si 0 proyectos; warn si 2+), envío de `project_id` en la mutación.
- [x] **F2** Script backfill
  - `backend/scripts/backfill_task_projects.py` (nuevo): dry-run por defecto, `--apply` para commit, `--client-id` para scope. Idempotente. Solo vincula cuando el cliente tiene exactamente 1 proyecto activo.
  - **Acción pendiente del usuario**: ejecutar `python -m backend.scripts.backfill_task_projects` (dry-run) y luego `--apply` cuando convencido.
- [x] **F3** Filtro "Sin Proyecto" en /tasks
  - Backend: nuevo parámetro `no_project: bool` en GET /api/tasks (`backend/api/routes/tasks.py`).
  - Frontend: chip "⚠️ Sin Proyecto" junto a los demás QA health (`frontend/src/pages/tasks-page.tsx`).
  - Test añadido: `test_list_tasks_no_project_filter`.

## P1 — Clarificar tiempo ✅
- [x] **F4** Tracked = canónica
  - `client-detail-page.tsx`: 5 cards → 4. Card "Tiempo tracked" pasa a ocupar 2 columnas (lg:col-span-2) con Estimado/Declarado como subtexto pequeño. Tooltip nativo `title=` explica las 3 fuentes.
- [x] **F5** Renombrado "Horas consumidas" → "Tiempo tracked" + tooltip
  - `project-detail-page.tsx:300-335`.
- [x] **F6** Cifras unificadas
  - Sin cambio de código: el backend ya usa `TimeEntry.minutes` para ambas vistas. Tras ejecutar F2 backfill, dashboard y página de proyecto coincidirán.

## P2 — Limpieza ✅
- [x] **F7** 14 pestañas → 10 grupos top-level con subtabs
  - `client-detail-page.tsx`: introducido sistema de grupos (Relación = Comunicaciones+Contactos, Outputs = SEO+Informes, Tiempo y dinero = Tiempo+Facturación+Facturas). URLs `?tab=xxx` siguen funcionando igual.
- [x] **F8** Burndown solo en no-recurrentes
  - `project-detail-page.tsx:337-345`: condición `!project.is_recurring` envuelve el chart. Para recurrentes se muestra una nota con link al dashboard mensual.
- [x] **F9** Dropdown cliente Timesheet fijo
  - `timesheet-page.tsx`: nuevas queries `allActiveClients` (siempre todos los activos) y `allActiveProjects` (filtrados por cliente seleccionado). Reemplaza el bug que derivaba clientes de tasks del usuario.
- [x] **F10** Badge "(según filtros)" en contador /tasks
  - `tasks-page.tsx:435`.
- [x] **F11** Etiqueta "(datos del mes seleccionado arriba, no acumulado)" en "Rentabilidad por cliente"
  - `dashboard-page.tsx`. Mejorado además el tooltip de "Real" para indicar que es tiempo tracked.
- [x] **F12** Tooltip `Est / Real` en /tasks
  - `tasks-page.tsx:628` y `:655`. Usa `InfoTooltip` ya disponible.

## Verificación

- TypeScript: ✅ `npx tsc --noEmit` sin errores
- Build: ✅ `npm run build` OK (4.36s)
- Backend tests: ✅ 372 pasados, 2 skipped (1 nuevo añadido)
- Frontend tests: ✅ 39 pasados

## Pendiente para el usuario

1. **Backfill** (uno-shot, prod): SIGUE PENDIENTE a 19 ago 2026. El script se
   ha probado en dry-run contra la copia local y funciona (es idempotente y solo
   vincula cuando el cliente tiene exactamente 1 proyecto activo). Falta lanzarlo
   contra producción:
   `DATABASE_URL='<la de Railway>' python -m backend.scripts.backfill_task_projects`
   (sin flags = dry-run; `--apply` para confirmar).
2. ~~**Despliegue Railway**~~: hecho (el código está en producción, verificado el 19 ago 2026).
3. **Verificación E2E en agency.magnifytools.com** después del deploy:
   - Crear tarea rápida → comprobar que aparece el campo Proyecto y se preselecciona Fit Generation
   - /timesheet → dropdown Cliente ahora muestra los 5 activos
   - /tasks → filtro "Sin Proyecto" funciona
   - /clients/1 → ver 10 grupos de pestañas en vez de 14
   - /projects/11 → ver "Tiempo tracked" en vez de "Horas consumidas" + aviso de proyecto recurrente
   - Dashboard → tabla con etiqueta "(datos del mes seleccionado)"
