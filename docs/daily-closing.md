# Cierre diario

El resumen diario guarda las notas antes de solicitar IA. Guardar, estructurar y compartir son acciones separadas. El dashboard abre el mismo editor de Resúmenes; mantiene la consulta del texto y los recibos existentes.

## Fuentes y texto

La consulta de hechos del día es de sólo lectura. Incluye tareas completadas en ese día civil, avances, esperas, próximos pasos y tiempo realmente registrado. El tiempo de tareas completadas y plantillas también cuenta. Un cronómetro en curso no se convierte en minutos estimados. La atribución de una tarea completada indica su responsable actual; no inventa quién la completó.

Las esperas y próximos pasos reflejan el estado actual al consultar. Seleccionar una fecha pasada no reconstruye estados históricos que la aplicación no registró.

Cada fuente lleva una identidad versionada, contexto de cliente/proyecto y enlace sujeto a permisos. Guardar valida las fuentes nuevas contra los datos actuales. Editar notas conserva las fuentes históricas seleccionadas, incluso si después cambia el origen. No se pueden seleccionar simultáneamente dos versiones del mismo hecho; se puede conservar la anterior o sustituirla por la actual.

La estructura opcional vincula cada afirmación a las fuentes seleccionadas o la identifica como nota libre. Los nombres de cliente y proyecto de afirmaciones vinculadas proceden de las fuentes. La respuesta se aplica sólo si el texto, revisión, estado y acceso siguen siendo válidos. Un error de IA conserva el borrador.

## Contrato de guardado

- `POST /api/dailys` guarda texto, fecha y claves de fuentes sin llamar a IA. Existe un único resumen por persona y fecha; repetir el mismo contenido recupera el mismo recurso.
- `GET /api/dailys/for-date?date=YYYY-MM-DD` recupera el resumen propio sin crearlo.
- `PUT /api/dailys/{id}` exige la revisión leída. Una edición obsoleta recibe `409` con la versión actual; repetir una edición ya aplicada no incrementa de nuevo la revisión.
- `POST /api/dailys/{id}/reparse` exige revisión y estructura explícitamente un borrador guardado. No mantiene bloqueos durante la llamada al proveedor.
- `DELETE /api/dailys/{id}?revision=N` sólo elimina borradores sin historial de entrega. Un resumen enviado o con recibos se conserva.

El navegador conserva el borrador por persona y fecha. Las notas no registran tiempo, no completan tareas y no provocan envíos. Los recibos siguen mostrando la intención y los fragmentos realmente entregados, independientemente del borrador actual.

## Migración y verificación

El arranque añade `revision`, `source_facts` y el índice único de persona/fecha bajo bloqueo transaccional. Si encuentra duplicados históricos, falla sin borrar ni fusionar datos. La preparación de un despliegue debe comprobar previamente esos duplicados. Readiness comprueba columnas e índice efectivo.

Las pruebas PostgreSQL cubren guardado idempotente, creación concurrente, edición obsoleta, revocación de acceso durante IA, envío durante IA, versiones de fuentes y preservación de recibos. Las pruebas de esquema cubren arranques concurrentes y rollback ante duplicados. No se envían comunicaciones de prueba a personas reales.
