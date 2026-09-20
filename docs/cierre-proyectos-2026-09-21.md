# Cierre y reapertura revisados de proyectos

Estado: P23 publicada y verificada en producción mediante PR35, revisión `f24647ce458d6beb602dc394fd8239be10b3a9a9`. No requiere migración ni modifica proyectos existentes.

Cerrar un proyecto como terminado o cancelado exige revisar sus tareas abiertas y cronómetros. La vista previa devuelve totales completos y muestras limitadas según los permisos de quien consulta. Si aparece trabajo nuevo entre revisión y confirmación, el servidor rechaza el cierre y devuelve la situación actual. Las transiciones archivadas dejan de aceptarse mediante el selector de estado genérico.

El cierre cambia sólo el estado del proyecto. Conserva tareas, horas, plantillas, pausas explícitas, recibos e informes. Las plantillas dejan de generar por el estado cerrado del proyecto. Reabrir vuelve al estado activo y permite continuar únicamente a las plantillas que no estuvieran pausadas; los recibos conservados impiden duplicar la ocurrencia de hoy y no se reconstruyen fechas pasadas.

Los escritores de tareas, restauración, cronómetro, operaciones masivas, comandos, automatizaciones heredadas y Deshacer aplican el mismo contrato. Los proyectos cerrados con trabajo antiguo conservan esa historia: se pueden corregir anotaciones y horas explícitas, completar o retirar deuda anterior, pero no crear o reactivar trabajo ni iniciar un cronómetro. Reabrir es una decisión separada. Deshacer una reapertura tampoco puede archivar si ahora existe trabajo abierto.

Las operaciones revalidan permisos y estado tras esperar los bloqueos. Cierre, recurrencia y Deshacer comparten orden de bloqueo; los escritores que ya tienen una tarea devuelven conflicto si el proyecto está cambiando, evitando una espera circular. `status: null` devuelve 422 antes de escribir; omitir el campo mantiene su comportamiento anterior.

La interfaz incorpora revisión, Archivo y reapertura. Se verificaron los recorridos de escritorio y móvil, conflictos, permisos y conservación de datos. Las automatizaciones genéricas permanecen ocultas según la decisión documentada; esta entrega no habilita reglas ni comunicaciones externas.

Evidencia final: CI 35543742673 sobre `ca0e0a0` con seis puertas correctas. Backend: 1.329 aprobadas y dos omitidas en la primera CI; la última revisión sólo añade dos regresiones de interfaz. Frontend final: 411 pruebas en 65 archivos, TypeScript y Vite. PostgreSQL acredita cero ocurrencias durante el cierre, una al reabrir, ninguna duplicada y conservación de pausas; Undo y semana completa tienen oráculos directos.

El navegador aislado comprobó bloqueos de tareas y cronómetro, conflicto ante cambios concurrentes, cierre → Archivo → reapertura y pausa manual conservada, a 390 y 1440 px. Se corrigió y comprobó la consulta obsoleta de revisión que se lanzaba después de cerrar con éxito.

Railway `16b83b79-f92e-4407-a7ae-7427e7f58e3c` terminó SUCCESS. Readiness devuelve la revisión publicada y el mismo esquema. Las 19 lecturas autenticadas contrastaron 11 proyectos: tres en Cartera y ocho en Archivo, con sus vistas previas correspondientes. Los hashes de tareas, clientes, proyectos, contactos, horas, informes e Inbox y el ledger permanecen iguales. Archivo y revisión de reapertura se inspeccionaron en producción; móvil 390/390 sin desbordamiento y consola sin errores. No se confirmó ninguna acción sobre proyectos reales ni se enviaron comunicaciones de prueba.
