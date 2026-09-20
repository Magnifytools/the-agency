# Hoy y búsqueda fiables

Estado: publicada y verificada en producción el 20 de septiembre de 2026. PR28 integrada como `8a3ba6ef7e658fd38bbdec80dc8dfdc486e84e25`.

“Todo el equipo” envía un ámbito explícito reservado a administradores. Antes, omitir el parámetro devolvía el trabajo personal pese a la etiqueta de equipo. “Mi trabajo” conserva su selección de tareas propias y sin asignar.

La búsqueda incluye tareas sin cliente y sólo expone nombres de cliente cuando la persona puede leer ese módulo. Las consultas seleccionan los campos mostrados, sin cargar grafos de relaciones. La paleta distingue carga, error, reintento y vacío, separa caché por persona y permisos y respeta módulos disponibles.

Hoy incorpora la próxima reunión personal, obtenida de eventos ya guardados sin iniciar sincronizaciones ni alertas. Las fechas se presentan como hora civil de la agencia; no se inventa un instante UTC para datos históricos que no guardaron el offset. Los eventos Google sólo se muestran si corresponden al calendario efectivo; las filas heredadas sin calendario identificado esperan a una sincronización que confirme su origen. La vista expone reconexión y última sincronización para no presentar datos retenidos como actuales.

Las acciones de Inbox se distribuyen en varias líneas cuando falta ancho. Las operaciones y permisos existentes se mantienen. No hay migración ni reescritura histórica en esta entrega.

Validación local: 1.119 pruebas backend aprobadas (2 omitidas), 307 frontend, build y Ruff correctos. PostgreSQL prueba los ámbitos reales, tareas sin cliente, ocultación de nombres, módulos desactivados, hora civil y ausencia de escrituras al leer reuniones. Navegador aislado: trabajo personal 2 tareas frente a equipo 3, navegación a la tarea exacta con teclado, reunión propia y acciones Inbox completas a 390 px. Una interrupción de red simulada prueba error y recuperación de búsqueda; no se alteran datos de producción.

Validación de publicación: los seis controles de CI de rama y main aprobaron. Railway confirmó la revisión exacta y `/api/ready` devolvió 200 con el esquema `20260920_inbox_recovery_v2`, sin migración nueva. Las lecturas de agenda distinguieron 4 tareas de arrastre personal y 14 del equipo; los resultados de búsqueda coincidieron con una consulta independiente. La próxima reunión devolvió ausencia y reconexión requerida, sin presentar información retenida como actual.

Se comprobaron las pantallas de Hoy, equipo y búsqueda a 390 y 1440 px. La consola no registró errores. Los conteos e indicadores de conservación de tareas y notas coincidieron antes y después; las horas, proyectos, clientes y resúmenes existentes permanecieron intactos. No se enviaron comunicaciones de prueba.

El objetivo completo sigue activo. La siguiente entrega aborda decisiones sobre el arrastre y retiro reversible con historia conservada; continúan los demás criterios de la auditoría, incluido el problema de Engine y la validación de uso con David y Nacho.
