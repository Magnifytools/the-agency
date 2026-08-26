# Progreso — Undo de los últimos 5 cambios

> 27 Ago 2026 — COMPLETADO

## Estado: hecho y verificado

1. [x] Modelo `ChangeLog` + `CREATE TABLE` en el lifespan de `main.py`
2. [x] `backend/services/change_journal.py` (captura por eventos ORM)
3. [x] Contextvar de actor en `deps.get_current_user`
4. [x] `backend/api/routes/changes.py` + registro en `_CORE_ROUTERS`
5. [x] Retención 90d en `startup/background_tasks.py`
6. [x] Tests: 17 unitarios + 13 de integración contra Postgres real
7. [x] Frontend: `changesApi`, `useUndo`, `UndoPanel`, atajo ⌘Z
8. [x] Verificación end-to-end en el navegador

## Verificación

- `pytest backend/tests` → **523 passed, 2 skipped** (sin regresiones)
- `npm run test` → 45 passed · `tsc --noEmit` limpio · `npm run build` OK
- Navegador (backend 8004 + frontend 5177, Postgres real):
  - cambiar estado de una tarea → aparece en el panel ↶ como
    "Tarea «QA Task 9d35b9» editada" → "Deshacer" la devuelve a Pendiente
  - ⌘Z deshace el último cambio y muestra el toast
  - ⌘Z con el foco en un input NO dispara el undo de la app (deshacer nativo intacto)
  - Sin errores en consola

## Hallazgos que valen para el futuro

- **El lifespan no ejecuta `create_all`.** Sólo `init_db` lo hace, y en
  producción no corre. La primera versión creó el índice pero no la tabla:
  `UndefinedTableError` en el arranque. Anotado en el CLAUDE.md del proyecto.
- **Client DELETE es soft delete** (status → finished), así que el undo de
  "desactivar cliente" es un simple update. Sale gratis.
- **El purgado duro de clientes** usa `sqlalchemy.delete()` masivo: no pasa por
  la capa ORM, no se registra y no se puede deshacer. Correcto: es irreversible
  por diseño y está protegido contra clientes con historial financiero.
- La zona horaria de los "hace Xh" del panel sale de Postgres (Europe/Madrid) y
  se compara contra la hora local del navegador. Es el comportamiento que ya
  tenía toda la app (campanita de notificaciones incluida), no algo del Undo.
