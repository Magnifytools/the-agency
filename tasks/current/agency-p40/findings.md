# Hallazgos P40

- Baseline PostgreSQL de ACL/procedencia: 1 prueba verde.
- Tras añadir el contrato, falla el detalle para el responsable sin `tasks`: recibe `content.sections.done[0].source_keys == ["task:9"]` aunque el catálogo ACL sólo conserva `aggregate:hours`.
- La recuperación no aplica al responsable: se limita al autor y devuelve 404; no se añadirá un caso de recovery inventado.
- El contrato final cubre `task:9` y `followup:10`: sólo las claves presentes en el catálogo ACL del lector se devuelven; el texto permanece igual.
