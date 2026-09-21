# Informes recuperables y fuentes por afirmación

P27 evita crear versiones duplicadas cuando se pierde la respuesta al preparar un resumen individual, una selección de clientes o un cambio de tono. El navegador guarda únicamente una clave opaca y los identificadores mínimos de la operación, separados por usuario. Nunca persiste el texto del informe en almacenamiento local. Antes de enviar, la clave debe quedar guardada; ante un resultado incierto, la interfaz comprueba el servidor y sólo permite reintentar exactamente la misma solicitud.

El servidor conserva la identidad de generación en el contexto privado del resumen y permite recuperarla únicamente al actor que la inició. Las llamadas al proveedor se ejecutan fuera de la transacción; antes de guardar se vuelven a comprobar permisos, política y fuentes bajo locks ordenados. Un error confirmado 4xx libera la operación; un timeout, corte de red o 5xx conserva la clave porque el resultado puede haberse guardado.

Cada afirmación generada puede declarar claves de fuentes validadas contra el catálogo recogido. La edición muestra esas referencias y enlaza tareas o proyectos sólo cuando el usuario puede leerlos. Si una persona cambia el título o la descripción, las claves de esa afirmación se vacían para no presentar el texto editado como certificado. Las versiones históricas sin catálogo se conservan y se identifican claramente como revisión manual.

No hay migración: se reutiliza `raw_context` para el catálogo público y una sección `_generation` que nunca sale en las respuestas. La recuperación no cambia períodos, estados de entrega ni versiones anteriores, y no envía nada al cliente o a Discord.
