# Progreso P40

- Plan creado a partir de la orden de implementación; no existía un plan P40 previo en los checkouts disponibles.
- Baseline PostgreSQL existente: verde (1 passed).
- Regresión ampliada: roja como se esperaba; el detalle expone `task:9` al responsable sin `tasks`.
- `_to_response` ahora filtra `content.source_keys` contra el mismo catálogo ACL proyectado, sin mutar la entidad ni el texto.
- Prueba focal verde y suite de recuperación/procedencia verde: 13 passed.
- Subconjunto PostgreSQL ampliado verde: 30 passed en recuperación, períodos y política. `git diff --check` limpio; pendiente sólo commit.
