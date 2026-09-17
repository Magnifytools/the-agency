# Proyectos y tareas en el trabajo diario

La ficha de proyecto muestra el responsable elegido, la próxima acción planificada y las esperas pendientes de revisión. El responsable es opcional y distinto del asignado a cada tarea. Las altas manuales, por plantilla, PDF y texto permiten elegirlo explícitamente; los documentos nunca lo asignan por inferencia. Los proyectos existentes siguen sin responsable hasta que se decida uno.

La próxima acción se deriva del conjunto completo de tareas. Se prioriza el compromiso con fecha más antigua (planificación o límite), después prioridad e ID; las atrasadas siguen visibles. Completadas, backlog y esperas no se presentan como próximas acciones. Si no hay ninguna, se explica la ausencia. Una espera conserva su motivo y fecha de revisión; al cambiar de estado deja de figurar en ese bloque sin borrar metadatos históricos.

El mismo panel de tarea se abre desde Hoy, listas, semana, proyecto y cliente. Incluye estado, planificación, responsable y contexto; descripción, seguimiento, recurrencia, dependencias, checklist, comentarios y archivos permanecen disponibles. Cambiar de cliente limpia proyecto y fase incompatibles. Una edición conserva el proyecto actual aunque esté cerrado.

El registro de horas es una acción separada. La fecha manual se muestra y puede editarse antes de guardar. Los lectores pueden consultar el historial; editar o borrar exige permiso y ser propietario del registro o administrador. Borrar requiere confirmación. Los errores de carga ofrecen reintento, y los envíos pendientes bloquean duplicados.

## Entregas externas

Daily y digest guardan la intención y muestran recibos reales por fragmento. En cola no significa enviado. Un resultado incierto no se reintenta automáticamente: requiere revisar el destino y confirmar una nueva intención. El contenido del borrador permanece separado del texto enviado. Véase [despliegue y contrato de entregas](durable-deliveries.md).

Esta entrega cubre envíos manuales de daily y digest. Recordatorios, otros emisores, incidencias unificadas y comandos naturales continúan en el plan. No se activan capacidades ocultas ni se reconstruyen datos históricos.

## Verificación

Pruebas con PostgreSQL aislado cubren propietario, usuarios activos, permisos, contrato de tareas y arranque sobre un esquema anterior. El arranque añade columna, índice y clave externa sin backfill; readiness comprueba el esquema efectivo. El ledger se verifica con transporte simulado y fallos de concurrencia, commit, timeout y permisos. Pruebas DOM y recorridos locales comprueban panel, seguimiento, registro de tiempo y móvil. Nunca se envían comunicaciones de prueba a personas reales.
