# Cierre y reapertura revisados de proyectos

Estado: P23 en validación local; producción sigue en P22. No requiere migración ni modifica proyectos existentes.

Cerrar un proyecto como terminado o cancelado exige revisar sus tareas abiertas y cronómetros. La vista previa devuelve totales completos y muestras limitadas según los permisos de quien consulta. Si aparece trabajo nuevo entre revisión y confirmación, el servidor rechaza el cierre y devuelve la situación actual. Las transiciones archivadas dejan de aceptarse mediante el selector de estado genérico.

El cierre cambia sólo el estado del proyecto. Conserva tareas, horas, plantillas, pausas explícitas, recibos e informes. Las plantillas dejan de generar por el estado cerrado del proyecto. Reabrir vuelve al estado activo y permite continuar únicamente a las plantillas que no estuvieran pausadas; los recibos conservados impiden duplicar la ocurrencia de hoy y no se reconstruyen fechas pasadas.

Los escritores de tareas, restauración, cronómetro, operaciones masivas, comandos, automatizaciones heredadas y Deshacer aplican el mismo contrato. Los proyectos cerrados con trabajo antiguo conservan esa historia: se pueden corregir anotaciones y horas explícitas, completar o retirar deuda anterior, pero no crear o reactivar trabajo ni iniciar un cronómetro. Reabrir es una decisión separada. Deshacer una reapertura tampoco puede archivar si ahora existe trabajo abierto.

Las operaciones revalidan permisos y estado tras esperar los bloqueos. Cierre, recurrencia y Deshacer comparten orden de bloqueo; los escritores que ya tienen una tarea devuelven conflicto si el proyecto está cambiando, evitando una espera circular. `status: null` devuelve 422 antes de escribir; omitir el campo mantiene su comportamiento anterior.

La interfaz incorpora revisión, Archivo y reapertura. Antes de publicar se verificarán los recorridos de escritorio y móvil, conflictos, permisos y conservación de datos. Las automatizaciones genéricas permanecen ocultas según la decisión documentada; esta entrega no habilita reglas ni comunicaciones externas.

Evidencia actual: primera suite backend conjunta, 1.317 aprobadas y 2 omitidas; suites dirigidas de cierre, permisos, concurrencia, Undo y rechazo de estado nulo. La comprobación adicional con el generador real acredita cero ocurrencias durante el cierre, una al reabrir, ninguna duplicada tras otro ciclo y conservación de pausas. Pendientes: suite final sobre todos los cambios, interfaz congelada, navegador aislado, CI y despliegue.
