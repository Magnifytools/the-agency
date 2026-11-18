# Estados de tarea (feedback de Nacho, 18 nov 2026)

## Lo que pide Nacho
- **Pendiente**: backlog sin fecha de inicio. No sale en el cierre del día.
- **En curso**: se está trabajando. Al llegar su fecha de inicio pasa sola a En curso
  y se queda ahí hasta que cambie de situación.
- **En espera**: depende de otras personas. Sale en el cierre (constancia).
- **En revisión**: esperando aprobación (nuestra o del cliente).
- **Hecho**: al registro.

"Fecha de inicio" = el campo **Planificada** (`scheduled_date`); `start_date` no se edita
en ningún sitio de la interfaz.

## Decisiones de David
1. Las tareas en backlog con la fecha ya pasada (Fit, mar-may 2026) → se les quita la
   fecha (quedan Pendiente sin fecha). No pasan a En curso.
2. Cierre del día: también las tareas En curso SIN fecha. En revisión, como estaba.
3. Poner a mano la fecha de hoy (o pasada) a una Pendiente → En curso al momento.

## Pasos
1. `task_lifecycle.apply_planned_start` (regla única) en `create_task` y `update_task`:
   - pendiente/backlog con Planificada <= hoy:
     - si cambió la fecha (o es alta) → En curso;
     - si lo que cambió es el estado (eligió Pendiente) → se quita la fecha;
     - si no cambió ninguna → nada (lo arregla el job).
   - Nunca en plantillas recurrentes ni retiradas.
2. Job diario `advanced_reset` (lock 5, 00:01 + arranque): además de devolver las
   avanzadas, pasa a En curso las pendientes cuya Planificada ha llegado.
3. `daily_facts`: fuera Pendiente/backlog de "próximos pasos"; En curso sin fecha entra
   ("En curso"); textos sin la palabra "Pendiente" ("Planificada el …", "Vencida el …").
4. Panel de tarea: aviso bajo el estado cuando la regla va a actuar al guardar.
5. Tests (unit + integración) y CLAUDE.md.
6. Datos: quitar la fecha a #441, #417, #395, #289, #276, #115.
