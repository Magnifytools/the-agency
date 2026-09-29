# Hallazgos

- `chrome-extension/popup.js#createTaskDirect` enviaba una tarea `in_progress` sin `assigned_to`.
- El selector global (`ActiveTimerBar`) consulta exclusivamente `assigned_to=me`, con estados operativos y `timer_eligible=true`; el selector de la propia extensión sigue el mismo ámbito.
- Mientras el timer está activo se muestra por `/api/timer/active`; al pararlo se recarga el selector y la tarea sin responsable ya no figura.
- La corrección debe expresar la intención en el contrato de creación (`assign_to_current_user`) y materializarla en el backend usando el usuario autenticado. Evita que la extensión tenga que leer o enviar un identificador de usuario manipulable y conserva el alcance normal de los listados.
- Las capturas directas ya creadas permanecen sin responsable. El ámbito `timer_scope=assigned_or_created`, válido únicamente junto a `assigned_to=me`, une tareas asignadas al actor con tareas sin asignar cuyo `created_by` es ese mismo actor; no cambia los listados generales.
