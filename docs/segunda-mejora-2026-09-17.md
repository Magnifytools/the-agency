# Segunda entrega: navegación e integridad

La aplicación organiza los accesos en Hoy, Trabajo, Clientes, Resúmenes y Ajustes. Hoy abre la agenda personal; Trabajo reúne tareas, proyectos, horas y capturas por aclarar. La gestión del equipo está en Ajustes. Las rutas anteriores siguen disponibles y los permisos y módulos ocultos se conservan. Búsqueda, captura y cronómetro permanecen accesibles en escritorio y móvil. La vista de tareas y los filtros de proyectos se conservan en la URL.

El listado de proyectos filtra antes de paginar y contar; el progreso se calcula a partir de las tareas actuales. El error de carga ofrece reintento. Convertir una nota en tarea exige permiso de escritura, valida su cliente/proyecto y bloquea la nota para que dos reintentos creen una sola tarea. El borrado masivo solo informa éxito después del commit.

Al cerrar o cambiar de sesión se cancelan las peticiones anteriores y se vacía la caché. Una respuesta 401 atrasada no expira la identidad nueva. Login y logout se serializan para evitar que una respuesta antigua borre la cookie recién creada.

El contexto del asistente respeta los permisos por módulo existentes. El briefing es personal por defecto; el ámbito de equipo exige administración. Las fuentes financieras requieren permiso y capacidad activa, incluyendo lecturas de hallazgos guardados y acciones por ID. Los hallazgos históricos ambiguos se conservan, pero quedan ocultos sin acceso financiero. La IA operativa no recibe esas fuentes. Una regeneración fallida conserva los hallazgos anteriores y un resultado sin incidencias es válido.

Se actualizan dependencias Python y se conserva compatibilidad con tokens HS256 anteriores, revocación, cookies y secretos del vault. La auditoría Python pasa a ser obligatoria en CI. El contenedor de producción se construye en CI antes de integrar. Detalle de dependencias en `python-dependencies.md`.

## Validación

- Backend conjunto:595 pruebas aprobadas,2 omisiones existentes; PostgreSQL real aislado.12 comprobaciones adicionales de permisos/migración/readiness aprobadas.
- Frontend:69 pruebas aprobadas; TypeScript y build de producción comprobados.
- Regresiones: más de25proyectos, filtros antes del conteo, completar/reabrir/borrar tareas, conversiones concurrentes, rollback, cambio de identidad, respuesta401 atrasada, cancelación y navegación autorizada.
- Vista local sintética de escritorio y móvil, cambio Hoy↔Trabajo y enlaces de proyecto; sin escrituras de prueba en producción ni envíos a terceros.
- El despliegue y la revisión exacta se acreditan en la PR y su CI. Esta entrega no cierra el objetivo completo: siguen pendientes fichas/altas, incidencias proactivas, resúmenes por período e instrucciones naturales.

## Migración y recuperación

El arranque añade valores `financial` y `operational_suggestion` al enum existente de insights. Readiness exige esos valores antes de aceptar tráfico. No modifica horas, atribuciones ni fechas históricas. El porcentaje histórico de proyectos se conserva en la base; las respuestas usan contadores actuales. Una reversión debe conservar los valores nuevos del enum y evitar que el código anterior interprete filas de tipos que no reconoce; no revertir solo el contenedor después de generar esos hallazgos sin revisar compatibilidad.
