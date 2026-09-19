# Resúmenes por cliente y confirmación de entrega

Estado: publicada y verificada en producción. PR19, revisión `1e667d231582e2f3052562f86683b262b58ff845`.

La preparación de resúmenes deja de depender de «Generar todos». Cada cliente puede tener una frecuencia semanal o mensual y una persona responsable. La configuración es explícita: la migración no activa clientes ni deduce compromisos a partir de informes antiguos. Se configura desde Cliente → Resúmenes.

En Resúmenes, la selección muestra el último período cerrado de cada cliente y explica las exclusiones: cliente inactivo o interno, configuración ausente o pausada, responsable no disponible, o período que ya tiene un informe. Una selección mixta conserva los períodos semanales y mensuales correspondientes. Preparar no envía el contenido al cliente ni a Discord.

El servidor comprueba de nuevo los permisos, la configuración y el período antes y después de generar. La generación individual y la selección comparten el bloqueo del cliente/período. Los resultados distinguen informes generados, omitidos y fallidos; un fallo no borra las versiones anteriores. El endpoint antiguo de generación masiva se retira al publicar el nuevo recorrido.

Preparar, compartir internamente y entregar al cliente son hechos separados:

- El historial conserva las versiones y permite cargar las anteriores a las veinte más recientes.
- Discord conserva sus propios recibos y se identifica como distribución interna.
- La entrega al cliente se confirma manualmente sobre una versión guardada. La app conserva quién la confirmó, cuándo y cualquier corrección posterior. No realiza un envío externo.
- Confirmar una versión anterior no confirma las posteriores. Los estados antiguos «enviado» se conservan como información histórica, sin convertirlos en prueba de entrega.

El responsable asignado puede acceder a los informes preparados por un administrador sin alterar quién los creó. Pausar la preparación no elimina ese acceso. Reasignar la responsabilidad o retirar permisos vuelve a aplicar las reglas de acceso; el autor conserva el acceso que le corresponda.

La vista de hechos distingue totales de muestras, progreso en el momento de generar y minutos acumulados. Los datos antiguos se presentan sin inventar totales ni atribuciones de proyecto. Los enlaces dependen de los permisos de lectura.

## Verificación

Las pruebas locales incluyen permisos, cambios durante la generación, selección de períodos distintos, conflictos de edición, confirmaciones concurrentes, claves idempotentes, migración aditiva y paginación. El recorrido integrado en navegador comprueba configuración semanal y mensual, preparación conjunta, edición con nueva versión, confirmación y revocación, acceso de lectura y recuperación de 27 versiones mediante paginación. Se utiliza la API y PostgreSQL reales de un entorno aislado, con un proveedor de redacción sintético. El frontend supera 225 pruebas y el build de producción. CI de la rama y de main aprobado: 858 pruebas backend (2 omitidas), 225 frontend y 42 de extensión. Imagen Linux y auditorías de dependencias aprobadas. Producción supera 42 lecturas autenticadas y la inspección visual a 390 y 1440 px; procesos de entrega reactivados tras comprobar la migración y retirar la instancia anterior. Las escrituras de prueba se realizan exclusivamente con datos sintéticos aislados.

La consulta de preparación mantiene cuatro lecturas de proyección, además de la lista inicial, al pasar de uno a treinta clientes con múltiples versiones. No carga los cuerpos completos de los informes. Los nuevos instantes de versiones, configuración y confirmaciones se guardan en UTC aunque PostgreSQL use otra zona horaria; los registros históricos no se reinterpretan.

El historial permite filtrar clientes inactivos, mientras la preparación individual ofrece clientes activos externos. El cronómetro respeta el permiso de registro de tiempo y no consulta tareas o clientes inaccesibles.
