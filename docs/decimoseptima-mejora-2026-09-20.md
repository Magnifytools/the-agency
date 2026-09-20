# Revisar pendientes conservando su historia

Estado: implementada y validada localmente; pendiente de CI y publicación. Producción continúa en P16.

Arrastre permite revisar cada tarea: reprogramar, dejar en espera con motivo y fecha, completar o retirar con motivo. Reprogramar cambia la planificación, conservando el plazo: una tarea con plazo vencido sigue apareciendo como atrasada. Las decisiones contrastan la revisión guardada; ante un cambio concurrente se conservan las entradas y se pide revisar la información actual antes de reintentar.

Retirar conserva el estado, las fechas, el proyecto, las dependencias y las horas. El historial Retiradas permite restaurar en cualquier momento, independientemente del Deshacer reciente. Las tareas retiradas salen de contadores operativos, siguiente acción, búsqueda y avisos, mientras sus horas y hechos históricos siguen en informes. No se atribuyen fechas de finalización a tareas antiguas.

No se puede retirar una plantilla recurrente, una tarea con cronómetro abierto o una tarea que bloquea trabajo activo. Mientras está retirada se permiten anotaciones, comentarios, archivos y correcciones de horas existentes; se bloquean nueva ejecución, nuevas horas y cambios operativos. Restaurar y Deshacer vuelven a comprobar dependencias y cronómetros bajo bloqueo transaccional. Las distintas entradas, incluidos comandos preparados, comparten esas reglas.

La migración añade dos columnas nullable y un contrato que exige fecha y motivo conjuntamente; no reescribe datos ni modifica migraciones publicadas. La respuesta recarga relaciones después de bloqueos ligeros para conservar nombres y checklist.

Validación local: 1160 pruebas backend aprobadas (2 omitidas), 316 frontend, compilación y Ruff correctos. PostgreSQL cubre upgrade, conservación, concurrencia, dependencias, cronómetros, comandos y Deshacer. El navegador aislado recorrió las cuatro decisiones, restauración, edición de anotaciones y horas, conflicto de revisiones, teclado y permisos de lectura. Las escrituras sólo utilizaron datos sintéticos.

El objetivo completo continúa: esta entrega no cierra los demás criterios de la auditoría.
