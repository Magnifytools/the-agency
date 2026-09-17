# Primera mejora de Agency — 17 septiembre 2026

**Entrega implementada y verificada localmente. La publicación se acredita mediante la revisión, CI y despliegue asociados.**

David autorizó iniciar las mejoras con Codex dirigiendo subagentes Sol y Terra. Sol implementó el dominio de tareas/horas; Terra la interfaz; Codex coordinó contratos, corrigió bordes durante la revisión, implementó alertas y realizó la integración y comprobación visual.

## Resultado para el usuario

- Hoy separa **Planificadas hoy, Arrastre, Sin planificar y Completadas hoy**. Cada grupo tiene consulta, total y paginación propios. Una tarea antigua no desaparece por estar fuera de las 25 más recientes. La fecha de finalización es real y respeta el día del navegador.
- Los filtros que no aplican a Hoy quedan fuera de esa vista. En móvil se ve trabajo en la primera pantalla, con título legible y estado debajo. Tablero y Semana tienen paginación explícita; la caché de Semana distingue su rango.
- Cliente, proyecto, responsable y fecha de planificación quedan visibles al crear/editar. Un único proyecto activo se propone para elegirlo; no se asigna sin intención. Un proyecto cerrado ya vinculado se conserva al editar. Los enlaces `?id=` abren la tarea.
- Capturar con fecha/responsable vacíos conserva esos valores. Guardar el título no cambia los minutos ni mueve el registro de tiempo a hoy. La edición explícita de duración preserva los registros de terceros y las fechas existentes; no permite reducir el total por debajo del tiempo que debe editarse desde sus registros originales.
- El daily deja de imputar estimaciones o 30 minutos por coincidencia de texto. Se mantiene el parseo y la publicación, incluido el fallback de texto sin parsear.
- Las recurrencias conservan proyecto, fase, estimación y creador. Se pausan cuando el cliente o el proyecto dejan de estar activos.
- Los avisos periódicos tienen identidad persistente por destinatario, entidad, condición y ciclo. Leerlos no crea otro aviso igual. Dos comprobaciones concurrentes tampoco lo duplican. Un ciclo nuevo puede generar un aviso nuevo.
- Facturación desactivada no inicia su job ni aparece en campana/contador/dashboard. Los registros históricos permanecen. Se ocultan también las superficies de cierre financiero incompatibles con el módulo desactivado.
- Abrir el enlace de un insight ya no lo marca automáticamente como actuado; sigue existiendo la acción explícita.

## Evidencia

- [Hoy en escritorio](../output/playwright/phase1/hoy-desktop.png).
- [Hoy en móvil, 390 × 844](../output/playwright/phase1/hoy-mobile.png).
- [Build](../output/playwright/phase1/frontend-build.log) y [51 pruebas frontend](../output/playwright/phase1/frontend-tests.log).
- [Suite conjunta backend: 537 aprobadas, 2 omitidas](../output/playwright/phase1/backend-tests.log).
- [14 regresiones finales dirigidas, después de la revisión](../output/playwright/phase1/final-regressions.log).
- [Prueba adicional de actualización de esquema](../output/playwright/phase1/schema-upgrade.log): 1 aprobada. Total de pruebas backend distintas aprobadas: **538**, incluidas **69 de integración PostgreSQL**.

Recorrido real en navegador local con datos sintéticos:

1. Iniciar sesión mediante formulario.
2. Abrir Hoy con más de 25 tareas; contador completo y botón para cargar las restantes; la tarea 30 aparece después de cargar más.
3. Editar el título de una tarea con 60 minutos. Comprobación SQL posterior: una sola entrada de 60 minutos y misma fecha original, 14 septiembre.
4. Completar desde la fila: baja el contador de Hoy y aumenta el de completadas sin recargar manualmente.
5. Crear tarea eligiendo la sugerencia de proyecto; verificar cliente/proyecto guardados.
6. Crear otra captura sin fecha/responsable; verificar ambos NULL y ausencia de duración inventada.
7. Revisar escritorio y móvil, corregir el título truncado y volver a capturar.

Se usaron tres bases nuevas exclusivas de esta tarea. No se modificaron datos de producción ni se hicieron envíos o generaciones de pago.

## Publicación y compatibilidad

El arranque añade de forma idempotente `tasks.completed_at`, su índice, `notifications.dedupe_key` y un índice único por usuario/clave. Se probaron las sentencias reales de arranque sobre tablas con forma antigua, ejecutándolas dos veces: conservaron las filas y aplicaron la unicidad.

Las tareas completadas antiguas mantienen `completed_at=NULL`; no se inventa una fecha a partir de `updated_at`. Las notificaciones antiguas no se borran: una comprobación puede adoptar una existente del ciclo actual. Las claves de comprobación se conservan al aplicar la retención de notificaciones leídas para impedir que reaparezca la misma condición por purgar su identidad.

Al publicar, comprobar arranque/migraciones, acceso, las cuatro consultas de agenda y contador de avisos con módulos actuales. Las comprobaciones de escritura —horas, completar y crear— se ejecutan con datos sintéticos aislados.

## Lo que queda para las siguientes entregas

Esta entrega no reconstruye la navegación completa, el sistema de incidencias activas/resueltas, los informes por período ni el asistente de instrucciones. La detección de parte de los avisos aún se ejecuta al abrir la campana; ahora es idempotente. Queda pasarla a un flujo proactivo común con estado de resolución.

Tampoco corrige automáticamente la atribución histórica de proyectos ni las entradas de tiempo antiguas: necesitan revisión y trazabilidad. Siguen pendientes los demás riesgos de la auditoría, entre ellos permisos de vías alternativas, separación de caché al cambiar identidad, versiones de digests y su fecha de finalización fuente. La nueva `completed_at` ya permite abordar después esos informes.

El siguiente bloque funcional es simplificar Hoy/Trabajo y la ficha de proyecto, con un siguiente compromiso claro por proyecto; después resúmenes y comandos naturales. La publicación de esta primera mejora es un paso separado de esas ampliaciones.

## Revisión adicional antes de publicación

- Enlaces de calidad del PM abren Todas con el filtro correspondiente. Calendario tiene paginación explícita y reinicia la página al cambiar de mes. Recorridos de escritorio/móvil comprobados.
- Las escrituras de tiempo y su total de tarea comparten transacción y orden de bloqueo. Los ajustes manuales se incluyen en Deshacer con su entrada de tiempo; se recalcula el total preservando registros posteriores. Un conflicto devuelve409 y permite reintentar. El tiempo derivado por cronómetro no se registra como un total independiente deshacible.
- La edición explícita de horas exige escritura de timesheet; guardar otros campos no exige ese permiso adicional.
- El arranque web deja de ejecutar seeds comerciales por nombres, limpieza QA o cambios de contraseña. Se retira también la invocación automática de init_db en Procfile; el script histórico queda para revisión separada.
- Railway usa /api/ready para comprobar conexión, columnas y semántica de índices únicos antes de cambiar tráfico. Pruebas reales cubren nombre legado equivalente, definición incorrecta y arranques repetidos que preservan datos.
- El CI exige PostgreSQL17 y pruebas frontend. El script predeploy es local y propaga fallos; el harness rechaza DB remotas/no identificadas como pruebas y la DB de aplicación antes de conectar.
- Actualización compatible del lockfile frontend:52pruebas, build y npm audit sin vulnerabilidades conocidas. La actualización de dependencias backend es otra entrega de la auditoría y permanece pendiente.
