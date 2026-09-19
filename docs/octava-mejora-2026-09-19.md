# Resúmenes por cliente y confirmación de entrega

Estado: implementación local en revisión; todavía sin publicar.

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

## Verificación pendiente de cierre

Las pruebas locales incluyen permisos, cambios durante la generación, selección de períodos distintos, conflictos de edición, confirmaciones concurrentes, claves idempotentes, migración aditiva y paginación. Antes de publicar quedan la revisión final de consultas, el recorrido integrado en navegador, la suite completa, CI y la comprobación de producción. Las escrituras de prueba se realizan exclusivamente con datos sintéticos aislados.
