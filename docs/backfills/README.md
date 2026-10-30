# Backfills aplicados en producción

Cambios masivos hechos con `UPDATE` directo: no pasan por el journal, así que
Deshacer (⌘Z) no los revierte. Cada uno deja aquí sus ids para poder volver atrás.

## 2026-10-19 · backfill_task_projects

- Fichero: `backfill_task_projects-20261019T055058Z.json`
- Qué: 576 tareas sin proyecto enlazadas al único proyecto activo de su cliente
  (421 Fit Generation, 109 SEO Retainer SSM, 46 Prime Casino). Aprobado por David.
- Quedaron sin proyecto 206: 197 de clientes sin proyecto activo y 9 sin cliente.
- Revertir un proyecto: `UPDATE tasks SET project_id = NULL WHERE id IN (<ids de ese proyecto>) AND project_id = <proyecto>;`
  (el `AND project_id` evita deshacer cambios hechos a mano después).
