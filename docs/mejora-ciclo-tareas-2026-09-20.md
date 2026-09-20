# Ciclo de tareas y revisión opcional

Estado: P22 implementada en local, pendiente de completar navegador, CI y publicación. Producción permanece en P21.

El trabajo se presenta en cinco grupos: Pendiente, En curso, En espera, En revisión y Hecho. Los estados almacenados y sus fechas se conservan. Backlog con fecha sigue distinguible; «Avancé hoy» mantiene el hecho del cierre diario y su retorno a En curso al cambiar de día.

Una nueva espera pide la respuesta pendiente, el responsable interno del siguiente paso y una fecha de revisión. Cambiar un título en una espera histórica incompleta no obliga a inventar datos. Una fecha de revisión vencida puede conservarse al modificar el motivo; elegir otra fecha exige hoy o un día posterior. Al salir de espera, motivo y seguimiento se limpian juntos. El cronómetro usa el mismo tratamiento de fechas de estado al retomar una tarea avanzada.

Cada proyecto puede activar revisión de tareas con un responsable elegido explícitamente. La opción está desactivada en todos los proyectos existentes. Bajo esa política, el responsable o un administrador completa el trabajo; los demás lo envían a En revisión. El servidor no convierte silenciosamente una petición de completar: explica qué acción se necesita. Las tareas sin política conservan su flujo, las plantillas recurrentes no requieren aprobación y cada instancia concreta sí aplica la política de su proyecto.

Los permisos se comprueban de nuevo después de las esperas de base de datos. Una revocación concurrente impide que terminen la edición o Deshacer. La planificación personal de Mi semana conserva su autorización específica: una persona puede poner fecha a su propia tarea sin recibir acceso general a editarla. La excepción no permite cambiar estado, proyecto ni horas.

Deshacer contrasta la política actual y el resultado real de restaurar los campos, incluidas ediciones posteriores que se preservan. No inventa fechas históricas de revisión ni finalización. Las operaciones masivas indican el resultado y motivo por tarea; un comando rechazado conserva su recibo de fallo sin afirmar que completó nada.

La migración añade solamente `projects.requires_task_review`, booleano no nulo y desactivado por defecto. No cambia estados, responsables, fechas, horas ni acuerdos. Los campos de contexto de revisión de la respuesta de tareas se derivan del proyecto; no se duplican en la base de datos y pueden leerse sin permiso para consultar el resto de la ficha de proyecto.

Verificación backend final: 1.285 pruebas aprobadas y 2 omitidas (295,82 s), incluidos los casos PostgreSQL y HTTP; Ruff y `git diff --check` correctos. Frontend, navegador, CI y despliegue siguen pendientes.

Evidencia local disponible: ensayo de esquema anterior y preservación, rutas HTTP y PostgreSQL reales, respuesta por tarea en cambios masivos, comandos rechazados, restauración de fechas antiguas, contención de política y revocación mediante el escritor oficial de permisos. La comprobación de producción previa encontró siete tareas backlog con fecha y cuatro esperas incompletas; permanecen sin modificar.

La entrega siguiente cubrirá cierre y reapertura revisables de proyectos y su archivo. La matriz completa del objetivo sigue vigente, incluidas decisiones de canal, revisión histórica y validación con David y Nacho.
