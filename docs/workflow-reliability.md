# Alta de proyectos, tareas e informes

Esta entrega reduce el alta de proyectos a nombre y cliente, con fechas y condiciones
opcionales. Plantillas, PDF y contexto de texto se eligen dentro del mismo flujo.
La tarifa mensual se conserva separada del presupuesto total; cambiar de modelo de
precio no envía campos que han dejado de ser visibles. El alta abre la ficha y permite
añadir una primera tarea sin exigir una fase ni inventar horas o fechas.

En Hoy y en el briefing se distingue trabajo personal de equipo. El ámbito personal
es el predeterminado, también para administradores. Consultar o compartir el ámbito
de equipo exige autorización. Los cambios de tareas, proyectos y tiempo actualizan
las consultas relacionadas; el arrastre optimista revierte la consulta exacta de
origen si la petición falla.

Las tareas completadas quedan plegadas en la ficha de proyecto. Los filtros y la
búsqueda siguen encontrándolas y permiten reabrirlas. Las filas tienen acciones de
teclado explícitas, muestran la ausencia de responsable y respetan permisos de
escritura. Un fallo de carga ofrece reintento y no se presenta como una lista vacía.

## Integridad y fechas

La validación común rechaza referencias incompatibles de cliente, proyecto y fase
en altas, plantillas, Inbox, Buffer y recurrencias. Las operaciones del motor de
automatizaciones conservado también usan esas validaciones. El motor respeta su
capacidad desactivada, no considera cumplida una condición cuyo dato falta y distingue
éxito, omisión y fallo. Se retira del catálogo el disparador sin productor `daily_check`.

Los informes consultan la fecha real de finalización. Las tareas antiguas sin fecha
conocida conservan NULL; editar un título no cambia el período del trabajo realizado.
Los totales se calculan antes de limitar las filas mostradas. Véase
[contrato temporal](temporal-contract.md) para fechas civiles, UTC, cambios de hora
y la distinción entre registros manuales y cronómetros.

El diario de Deshacer respeta los límites de transacciones y SAVEPOINT: una acción
revertida no publica un cambio deshacible, y un SAVEPOINT confirmado no adelanta la
confirmación de la transacción exterior. El almacenamiento del diario sigue siendo
asíncrono; esta entrega no promete un recibo durable para comandos aún no implementados.

## Salud de clientes

Una fuente oculta o no autorizada queda sin medir. La ausencia de tareas o de
resúmenes recientes tampoco equivale a buena o mala salud. Los riesgos observados
siguen visibles aunque falten fuentes para una valoración global. Se muestran las
observaciones que sustentan los factores; los costes requieren los módulos y permisos
financieros apropiados. La puntuación conservada es orientativa y no sustituye una
política de informes acordada ni el seguimiento de compromisos del proyecto.

## Extensión 2.1.2

Los selectores recorren todas las páginas de clientes, proyectos y tareas. Un fallo
intermedio conserva las opciones anteriores y permite reintentar. Las respuestas,
mensajes demorados y borradores quedan aislados por sesión; una petición antigua no
puede cerrar una cuenta nueva ni modificar sus controles. Los cronómetros aceptan
instantes UTC explícitos y conservan el acumulado al pausar.

El CRX se firma con la identidad existente. El ZIP de instalación contiene solo los
archivos de ejecución e iconos. Las pruebas usan APIs de Chrome y proveedores
simulados; no envían notas ni notificaciones a personas reales.

## Límites de esta entrega

Los datos históricos ambiguos se conservan. No se infieren asignaciones, horas,
finalizaciones ni acuerdos comerciales. Las entregas externas durables, las
incidencias unificadas, la cadencia por cliente y las instrucciones naturales siguen
siendo entregas posteriores del plan de implementación.
