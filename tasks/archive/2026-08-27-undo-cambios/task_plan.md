# Undo de los últimos 5 cambios — The Agency

> Iniciado: 27 Ago 2026

## Objetivo
Poder deshacer los últimos 5 cambios que ha hecho el usuario logueado, desde un
panel en la barra lateral + atajo Cmd/Ctrl+Z.

## Alcance acordado con David
- Entidades: **Task, Project, Client, Lead, GrowthIdea** (operativo).
  Fuera: finanzas (módulos "no tocar"), entidades generadas por IA.
- UI: panel con historial de los 5 últimos + botón "Deshacer" por entrada,
  más Cmd+Z (Ctrl+Z en Windows/Linux) para deshacer el más reciente.

## Diseño

### Captura (backend/services/change_journal.py)
Eventos ORM a nivel de `Session` (`before_flush` / `after_flush` / `after_commit`),
NO llamadas explícitas en cada ruta:
- `before_flush`: snapshot de columnas (create → after, update → before/after de
  las columnas que cambian de verdad, delete → before completo).
- `after_flush`: rellena el PK de los INSERT (ya asignado).
- `after_commit`: escribe las filas de `change_logs` en una sesión aparte
  (best-effort, igual que UsageTrackerMiddleware). Un fallo aquí nunca rompe la
  respuesta al usuario.
- Solo se registra si hay **actor** (contextvar puesta por `get_current_user`).
  Así los barridos nocturnos, seeds y scripts no ensucian el journal.

### Modelo `ChangeLog` (tabla `change_logs`)
user_id, entity_type, entity_id, action(create|update|delete), label,
before_data JSONB, after_data JSONB, undone_at, undone_by.

### Undo (backend/api/routes/changes.py)
- `GET /api/changes/recent?limit=5`
- `POST /api/changes/{id}/undo`
- Semántica inversa: create → borrar; update → restaurar columnas; delete → reinsertar.
- Se comprueba permiso de escritura del módulo correspondiente en el momento del undo.
- **Detección de conflicto**: si el valor actual de una columna ya no coincide con
  `after_data`, otro cambio la ha tocado después → esa columna NO se restaura y se
  informa. Si no queda nada que restaurar → 409.
- Deshacer un undo no se re-registra como cambio deshacible (evita bucles).

### Frontend
- `changesApi` en `lib/api.ts`
- `components/layout/undo-panel.tsx` (icono historial junto a la campana)
- Atajo global Cmd+Z en `app-layout.tsx`, ignorado si el foco está en un input.

## Pasos
1. [ ] Modelo ChangeLog + migración en lifespan de main.py
2. [ ] Servicio change_journal (captura por eventos ORM)
3. [ ] Contextvar de actor en deps.get_current_user
4. [ ] Rutas /api/changes + registro en main.py
5. [ ] Retención en background_tasks
6. [ ] Tests backend (captura, undo de los 3 tipos, conflicto, permisos)
7. [ ] Frontend: api + tipos + panel + Cmd+Z
8. [ ] Verificación end-to-end
