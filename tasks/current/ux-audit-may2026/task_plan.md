# Plan — Fix Auditoría UX Mayo 2026

**Origen**: auditoría 2026-05-22 sobre timetracking/proyectos/tareas en Agency (caso Fit Generation: 194 tareas, 169 huérfanas sin proyecto).

**Objetivo**: arreglar las 12 inconsistencias documentadas en `~/.claude/projects/-Users-david-Public-C-digo/memory/project_agency_ux_audit_may2026.md`.

## Estrategia

- 3 olas P0 → P1 → P2 (priorización ya definida)
- Cada ola: backend si toca, frontend, type-check, build, screenshot/verificación E2E vía Chrome MCP
- Crear tests cuando toquemos lógica de datos críticos (cambio de modelo de horas)

## P0 — Sangrado (vincular tareas a proyectos)

1. **F1** Modal "Crear tarea rápida" → añadir campo Proyecto con auto-preselección
   - Frontend: `frontend/src/components/QuickTaskModal*.tsx` (por confirmar)
   - Lógica: si el cliente seleccionado tiene exactamente 1 proyecto activo → preseleccionar; si tiene varios → mostrar select; si 0 → opcional
2. **F2** Backfill SQL: vincular tareas existentes con cliente único proyecto
   - Script en `backend/scripts/backfill_task_projects.py`
   - Solo vincular cuando `cliente.proyectos_activos.count == 1` (seguro)
   - Imprimir resumen antes de commit, requerir flag `--apply`
3. **F3** Filtro "Sin proyecto" en `/tasks`
   - Frontend: añadir botón chip junto a "Sin Asignar", "Sin Fechas", etc.
   - Backend: parámetro `?project_id=null` o `?no_project=true`

## P1 — Clarificar modelo de tiempo

4. **F4** Decidir UNA métrica canónica
   - Decisión: **Tiempo Tracked** (timesheet real) es la fuente de verdad
   - "Tiempo Estimado" pasa a tooltip de "Tracked" (solo cuando hay)
   - "Tiempo Real" deprecado (el campo `actual_hours` declarado al cerrar tarea queda como dato secundario en task detail)
5. **F5** Renombrar "Horas consumidas" en página proyecto a "Tiempo tracked"
   - Tooltip: "Suma de tiempo registrado en timesheet para tareas vinculadas a este proyecto"
   - Backend: cambiar fuente del cálculo de `estimated_hours` agregadas a `time_entries.duration_minutes` agregadas
6. **F6** Unificar cifras dashboard ↔ página proyecto
   - Ambas deben usar el mismo endpoint/query subyacente

## P2 — Limpieza

7. **F7** Reducir 14 pestañas del cliente
   - Agrupar: "Económicos" (Tiempo+Facturación+Facturas), "Outputs" (SEO+Informes), "Relación" (Contactos+Comunicaciones)
   - Resultado: 8 pestañas (Ficha, Actividad, Tareas, Proyectos, Panel, Relación, Outputs, Económicos, Recursos, Ajustes) — revisable
8. **F8** Burndown chart desactivado en proyectos recurrentes
   - Sustituir por "Carga este mes vs presupuesto"
9. **F9** Fix dropdown Cliente en Timesheet
   - Investigar por qué solo muestra 2/5 clientes activos
10. **F10** Sincronizar conteo tareas (badge "(N activas)")
11. **F11** Filtro mensual del dashboard: etiqueta clara "del mes" vs "acumulado"
12. **F12** Tooltip en columna "EST / REAL" de /tasks

## Verificación

- `npx tsc --noEmit` después de cada bloque
- `npm run test` después de cada bloque
- `python -m pytest tests/ -v` después de cada bloque
- Manual E2E vía Chrome MCP en agency.magnifytools.com para cada fix completado

## Errores conocidos a vigilar

- bcrypt pinned 4.1.3 (no actualizar)
- `Base.metadata.create_all` no agrega columnas → usar `ALTER TABLE ADD COLUMN IF NOT EXISTS` en `main.py` lifespan
- No tocar módulos financieros custom (se reemplazan por Holded)
