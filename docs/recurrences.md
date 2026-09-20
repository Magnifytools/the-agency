# Recurrencias y ciclo mensual

Una plantilla describe el trabajo que se repite. Cada fecha que corresponde al
calendario crea una tarea independiente, que se puede completar, reprogramar o
borrar sin modificar la regla de la plantilla.

## Calendarios

- Diaria: de lunes a viernes.
- Semanal: el día elegido, de lunes a viernes.
- Cada dos semanas: el primer día elegido a partir de la fecha indicada, y después cada catorce días.
- Mensual: el día elegido, entre el 1 y el 28.

La fecha de fin es inclusiva. Una pausa conserva el calendario y las tareas ya
creadas. Al reanudar, la siguiente reconciliación comprueba si corresponde crear
la tarea de hoy; no recupera fechas pasadas. El proceso corre al arrancar y cada
cinco minutos, usando la fecha civil de la agencia.

Las plantillas bisemanales antiguas sin fecha de referencia mantienen su regla
histórica de semanas ISO pares. Cambiar a un calendario con fecha de referencia
es una decisión explícita; la interfaz permite comparar las fechas antes de
guardar. Editar el título conserva la regla existente.

Un cliente o proyecto inactivo bloquea nuevas tareas. La vista muestra ese
motivo. Las reglas inválidas tampoco generan tareas.

## Identidad de cada tarea generada

`scheduled_date` representa el día de trabajo elegido por el usuario.
`recurrence_occurrence_date` conserva la fecha que originó una nueva tarea.
Reprogramar cambia únicamente el día de trabajo.

`task_recurrence_occurrences` conserva un recibo único por plantilla y fecha.
La creación de la tarea y el recibo ocurre en la misma transacción, con bloqueo
de la plantilla e índices únicos. Si se borra la tarea, el recibo conserva la
fecha consumida y su referencia a la tarea pasa a NULL. La reconciliación no
resucita tareas borradas. Una plantilla con historial se pausa o se termina;
su borrado no debe destruir el registro de ocurrencias.

La migración añade columnas y tabla sin atribuir fechas a tareas históricas.
El generador reconoce también los hijos antiguos por su fecha planificada
actual y conserva un recibo cuando los observa para el día de hoy; no intenta reconstruir su fecha original ni rellenar meses anteriores.
Los trabajos automáticos conservan el creador de la plantilla, usan el escritor
común y no se atribuyen como una acción manual deshacible.

## Proyectos recurrentes

La ficha muestra el mes civil seleccionado, las tareas planificadas, las
finalizadas con fecha de finalización conocida y las horas registradas.
Los dos contadores de tareas son poblaciones distintas: no se dividen para
inventar un porcentaje de cumplimiento. Las horas se calculan por proyecto,
incluidos registros asociados a tareas terminadas; otro proyecto del mismo
cliente no aporta horas a este ciclo.

El presupuesto es el mensual efectivo actual. Al consultar meses anteriores
se presenta como referencia actual, porque no existe un histórico de acuerdos
que permita reconstruir el presupuesto pactado de aquel mes.

## Verificación y despliegue

La migración es transaccional y no elimina datos para satisfacer un índice.
Readiness verifica las columnas, la unicidad por ocurrencia y que borrar una
tarea conserve el recibo. Las pruebas PostgreSQL cubren conservación de datos,
concurrencia, reprogramación, borrado y aislamiento entre proyectos.

Antes de publicar se comprueban las plantillas existentes y sus ámbitos en
modo lectura. La comprobación de escrituras y de generación usa una base de
datos sintética aislada. No se envían comunicaciones de prueba a personas.

Al borrar un proyecto, sus plantillas quedan pausadas antes de desvincular las
tareas. El borrado irreversible de un cliente elimina sus recibos sólo si todo
el conjunto de plantillas e hijos pertenece al cliente. Si hay vínculos con
otro cliente, se rechaza la operación sin realizar la limpieza. Generación y
borrados de ámbito comparten un bloqueo transaccional. Deshacer el borrado de
un hijo con fecha de ocurrencia conocida restaura también su vínculo al recibo.
