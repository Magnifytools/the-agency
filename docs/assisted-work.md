# Trabajo asistido por comandos

The Agency acepta un conjunto acotado de instrucciones en español desde la app y la extensión. No es un chat general ni interpreta cualquier frase con IA. El servidor reconoce una lista cerrada de operaciones, resuelve entidades accesibles para el usuario, aplica los mismos permisos y servicios que los formularios y guarda un recibo durable.

## Operaciones admitidas

Los nombres entre comillas protegen palabras como `para`, `con` o `en`. Se recomiendan siempre que el título o nombre contenga una preposición.

### Crear una tarea

```text
Crea tarea Revisar propuesta
Crea tarea "Hablar con Ana para el lanzamiento"
Crea tarea "Revisar home" en proyecto "Web nueva"
Crea tarea "Revisar home" para cliente "Acme"
Crea tarea "Revisar home" asignada a "Nacho"
Crea tarea "Revisar home" en proyecto "Web nueva" para mañana
Crea tarea "Revisar home" sin fecha
```

Calificadores admitidos:

- `en proyecto <nombre>`
- `para cliente <nombre>`
- `asignada a <nombre completo o short_name exacto>`
- `para|el hoy|mañana|<día de semana>|AAAA-MM-DD`
- `sin fecha`

Proyecto y cliente se validan juntos. Si solo se indica el proyecto, el servidor conserva su cliente real. Si no se indica destino, responsable o fecha, no se inventan.

### Crear un proyecto

```text
Crea proyecto "Web nueva" para cliente "Acme"
Crea proyecto "Web nueva" para cliente "Acme" responsable "Nacho"
Crea proyecto "Web nueva" para cliente "Acme" responsable "Nacho" fecha objetivo 2026-10-02
```

El cliente es obligatorio. `responsable` y `fecha objetivo` son opcionales y solo se guardan si aparecen de forma explícita. Este comando no infiere tarifa, presupuesto, alcance ni otros campos comerciales.

### Completar, reprogramar y cambiar prioridad

```text
Completa la tarea "Revisar propuesta"
Reprograma la tarea "Revisar propuesta" para mañana
Reprograma la tarea "Revisar propuesta" para próximo viernes
Reprograma la tarea "Revisar propuesta" para 2026-10-05
Reprograma la tarea "Revisar propuesta" sin fecha
Cambia la prioridad de la tarea "Revisar propuesta" a urgente
```

Reprogramar modifica `scheduled_date`. No cambia el deadline `due_date`. `sin fecha` limpia la planificación de forma explícita.

### Registrar tiempo manual

```text
Registra 45 minutos en la tarea "Revisar propuesta"
Registra 45 minutos en la tarea "Revisar propuesta" hoy
Registra 45 minutos en la tarea "Revisar propuesta" el 2026-09-18
Registra 45 minutos en la tarea "Revisar propuesta" el viernes
```

La fecha puede escribirse directamente después de la tarea o precedida por `el`/`para`. La duración debe estar entre 1 y 1440 minutos. Se atribuye al usuario autenticado; el comando no permite registrar tiempo en nombre de otra persona. Una fecha explícita es una fecha civil del calendario operativo. Si se omite, se usa el día de negocio actual.

### Consultar trabajo

```text
Consulta prioridades
Consulta bloqueos
Consulta prioridades del equipo
```

Por defecto se consulta el trabajo asignado al actor. El ámbito `del equipo` es explícito y requiere administración. Se excluyen plantillas recurrentes y el resultado incluye total y paginación real.

## Ambigüedad y fechas

Una coincidencia exacta única puede continuar. Si existen varias tareas, proyectos, clientes o personas con el mismo nombre, el recibo devuelve opciones; el usuario elige una y el servidor vuelve a validar permisos y estado antes de escribir.

Un título sin comillas que contiene `con`, `para` o `en` requiere confirmación para evitar que un calificador se convierta silenciosamente en parte del título o al revés. Los marcadores dentro de comillas siempre forman parte del nombre.

Las fechas se calculan con la zona de negocio configurada, actualmente `Europe/Madrid`, y se guardan como fecha ISO absoluta en la intención. Un replay posterior no recalcula `mañana`. Si hoy es viernes, `viernes` ofrece hoy y el viernes siguiente; `este viernes` y `próximo viernes` expresan la elección directamente.

Cuando la frase no pertenece a la lista admitida, contiene un actor no soportado o deja un calificador sin interpretar, el servidor pide reformular o devuelve un recibo fallido. Nunca convierte silenciosamente el resto del texto en una orden diferente.

## Permisos, contexto y atomicidad

Los permisos se evalúan con el usuario autenticado al crear y al resolver el comando. Las búsquedas solo consideran entidades operativas admitidas: clientes activos, proyectos activos o en planificación, usuarios activos y tareas que no sean plantillas recurrentes.

La app o extensión puede adjuntar un contexto estructurado:

```json
{
  "url": "https://example.test/page",
  "title": "Título visible",
  "selection": "Texto seleccionado"
}
```

Ese contexto se conserva como referencia y se muestra en el recibo. No se concatena con la instrucción, no modifica la intención y no concede permisos. El texto de una web o documento no se trata como una orden.

La mutación de dominio, el `ChangeLog` y el resultado del recibo comparten una transacción. Si la escritura o el journal fallan, se revierte todo. Un rechazo de permisos durante una resolución queda registrado como recibo `failed` sin aplicar la operación.

Los cambios reversibles enlazan `change_log_id` y exponen `undo_available`. Deshacer usa el servicio de Undo y sus comprobaciones de permisos y conflictos. Las consultas no ofrecen Undo. El recibo no promete revertir acciones externas; los comandos actuales no publican ni envían a canales externos.

## Recibos e idempotencia

`POST /api/commands` requiere una `request_key` de 16 a 64 caracteres. La pareja usuario + clave es única:

- misma clave y mismo payload: devuelve el recibo existente sin repetir la operación;
- misma clave y payload distinto: responde `409`;
- los pasos de resolución y ejecución llevan su propia clave y la revisión esperada;
- una elección obsoleta o un recibo que ya avanzó responde `409`.

Estados posibles: `needs_input`, `needs_review`, `executed` y `failed`. `needs_review` se reserva para planes revisables que tengan una ejecución real; las operaciones fuera del alcance no muestran un botón de ejecución ficticio.

`result.applied` guarda los valores realmente aplicados. `result.applied_labels` guarda, dentro de la misma transacción, las etiquetas visibles asociadas a `project_id`, `client_id`, `owner_id`, `assigned_to` y `user_id`. Son un snapshot: renombrar después una entidad no reescribe el recibo ni obliga a la UI a consultar nombres adicionales. `created_at` y `updated_at` se serializan como instantes UTC con sufijo `Z`.

Endpoints:

- `POST /api/commands`
- `POST /api/commands/{id}/resolve`
- `POST /api/commands/{id}/execute`
- `GET /api/commands/{id}`
- `GET /api/commands/{id}/query?page=1&page_size=25`
- `GET /api/commands?page=1&page_size=25&status=executed`

## Esquema y despliegue

Los recibos viven en `command_receipts`. La tabla contiene actor, clave y hash de petición, canal, contexto, texto original, intención, prompt, resultado, error, revisión, replays de pasos y el enlace opcional al `ChangeLog`. El índice único `(user_id, request_key)` aplica la idempotencia también bajo concurrencia.

El arranque ejecuta `ensure_command_schema` antes de servir peticiones. La actualización de esquema debe terminar correctamente antes de habilitar las rutas o los consumidores de comandos; un fallo de preparación bloquea el arranque en lugar de dejar una aplicación parcialmente compatible. Esta preparación crea estructura, índices y claves, pero no modifica recibos históricos ni datos de dominio.
