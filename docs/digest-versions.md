# Períodos, hechos y versiones de resúmenes

El período de un resumen es el intervalo civil inclusivo `period_start`–`period_end`, en Europe/Madrid. Si no se indican límites, la generación propone la última semana completa, de lunes a domingo. Deben enviarse ambos límites; un intervalo invertido o incompleto devuelve 422. La fecha de generación es un instante UTC independiente.

La etiqueta del período se deriva de esas fechas en respuestas, vistas previas y nuevas entregas. El texto generado por IA no puede reemplazarla. Los registros históricos se leen con esa etiqueta sin reescribir su contenido almacenado ni sus recibos de entrega anteriores.

Generar un resumen conserva los anteriores, incluso borradores del mismo cliente o período. `PUT /api/digests/{id}` devuelve la misma versión si el contenido y tono no cambian tras normalizarlos. Un cambio efectivo crea otra fila en estado borrador y devuelve su nuevo `id`. Los consumidores deben usar ese ID para editar, previsualizar o enviar la versión resultante. El autor, contenido y recibos de la versión original permanecen intactos.

El editor conserva también la sección de métricas. Cambiar el tono requiere confirmar y guarda primero las ediciones manuales; si la generación falla, ese borrador sigue disponible. Un guardado tardío no desplaza al usuario desde otro informe. Las vistas previas pertenecen a una versión concreta.

El contexto de generación V2 agrupa hechos por proyecto, con un grupo separado para tareas sin proyecto y referencias históricas no resueltas. Incluye proyectos actuales y proyectos cerrados con finalizaciones u horas en el período. Sus totales corresponden a ese contexto incluido. El progreso está etiquetado como actual; las tareas completadas y horas usan el período solicitado. Las plantillas de recurrencia no cuentan como trabajo, pero los minutos reales registrados históricamente sobre ellas se conservan.

El colector usa ocho consultas con proyecciones y agregados, y limita cada muestra de tareas a diez por grupo. Los totales son independientes de las muestras. Los contextos antiguos siguen siendo legibles para regeneración.

La política de cadencia por cliente, selección revisable de clientes para generación múltiple y procedencia del marcado manual de entrega continúan como trabajo posterior. Esta entrega preserva versiones; no convierte todos los clientes activos en una obligación de envío.
