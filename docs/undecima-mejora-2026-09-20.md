# Recurrencias explicables y ciclo mensual por proyecto

Publicada mediante [PR22](https://github.com/Magnifytools/the-agency/pull/22), revisión `e97a0b2a9df0ff8e731af10e2bf3716e49f5dbbb`.

Las plantillas muestran su regla, estado, motivo de bloqueo y próximas fechas. Se pueden pausar y reanudar. Las reglas bisemanales heredadas conservan su calendario; cambiarlo requiere comparar las fechas actuales y propuestas antes de guardar. El panel distingue la fecha de generación de una instancia de su fecha de trabajo.

La generación usa las operaciones comunes y conserva un recibo por plantilla y fecha. Reprogramar o borrar una instancia no vuelve a generarla; Deshacer recupera su vínculo. El proceso reconcilia el día actual al arrancar y cada cinco minutos. La migración es aditiva, sin rellenar días pasados ni reinterpretar fechas históricas. Véase el [contrato de recurrencias](recurrences.md).

Los proyectos recurrentes muestran el ciclo mensual: tareas planificadas, completadas dentro del período y horas reales del proyecto. Las poblaciones se presentan separadas y las horas de otros proyectos del mismo cliente quedan excluidas. El presupuesto vigente se identifica como referencia actual también al consultar meses anteriores.

Verificación: CI de rama `35510524683` y de main `35510730872` aprobadas, con 964 pruebas backend, dos omitidas, 270 de interfaz y 42 de extensión. Seguridad, lint, build y contenedor correctos. PostgreSQL cubre concurrencia, migración, reprogramación, borrado, Deshacer, permisos y volúmenes superiores a mil filas.

El recorrido aislado comprobó comparar calendarios, guardar, pausar, reanudar, generar, reprogramar, borrar y deshacer con API y base de datos reales. Producción se verificó mediante readiness, esquema, lecturas de recurrencias y ciclos, comprobaciones generales de API y colectores de informes. La comparación de los campos anteriores de tareas confirma su conservación. Las pantallas cargadas de escritorio y móvil se revisaron sin desbordamiento ni errores de consola observados. No se enviaron comunicaciones de prueba ni se modificó trabajo real.

El objetivo completo continúa con instrucciones compuestas, consulta de decisiones y el resto de la auditoría. Queda registrado un ajuste de interfaz: la vista de plantillas aún muestra filtros y contadores de trabajo ordinario que deben adaptarse a esa vista.
