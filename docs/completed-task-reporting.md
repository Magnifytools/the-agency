# Fechas de tareas completadas en informes

Los informes atribuyen una tarea a un período exclusivamente mediante
`Task.completed_at`. Editar después el título, la descripción u otro campo no
cambia el período informado. Al reabrir una tarea se borra `completed_at`; al
completarla de nuevo se registra una fecha nueva. Las tareas históricas con
`completed_at = NULL` se consideran de fecha desconocida y no se incluyen en
ningún período.

`completed_at` se guarda como UTC sin información de zona, igual que el resto
de timestamps históricos de este backend. Los resúmenes automáticos diario y
semanal convierten los límites civiles de `Europe/Madrid` a UTC antes de
consultar. El prefill interactivo del daily y los períodos elegidos por fecha
en digests e informes de cliente mantienen la convención UTC que ya usaban;
todavía no existe una zona
horaria configurable por cliente. Cambiar esa política requiere definir antes
la zona de cada cliente o informe para no reinterpretar datos históricos.

Los límites usan intervalos semiabiertos (`inicio <= completed_at < fin`) para
que una tarea no aparezca en dos períodos adyacentes. Cuando una salida muestra
solo las primeras tareas, el contador se calcula sin ese límite y la lista se
presenta como una selección.
