# Cambios visibles y recuperación de datos

Estado: implementación local P20, pendiente de publicación. La versión vigente continúa siendo P19 (`ea44b53`).

Renombrar, finalizar o modificar un cliente refresca las vistas operativas que usan sus datos: listas, fichas, proyectos, tareas, horas, cronómetros, salud y búsqueda. Los cambios de proyecto también actualizan los resultados de búsqueda. Al iniciar un cronómetro desde el panel, los otros controles reciben inmediatamente el estado compartido.

Las consultas revisadas de Clientes, salud del cliente, registros de hoy, informes de horas por cliente/proyecto, cronómetros y progreso distinguen un error de una lista realmente vacía. Los fallos muestran un aviso y permiten reintentar. La caché se conserva internamente, pero sus datos se ocultan hasta que una respuesta correcta confirme que siguen disponibles; un acceso revocado seguido de un fallo de red o una nueva visita no recupera información antigua. No se muestran cero horas ni ausencia de cronómetro como consecuencia de un error.

Los controles de tiempo requieren permiso de escritura y un estado conocido del cronómetro. Los selectores dejan de mostrar opciones cuyo permiso de lectura se haya retirado. El gráfico de progreso explica la carga, el fallo, la ausencia de tareas y la falta de días suficientes para mostrar una evolución.

Esta entrega cambia la interfaz y su caché. No introduce migraciones ni modifica estados, horas, fechas o asignaciones históricas. El flujo compuesto de alta de cliente con contactos y proyecto mantiene una deuda separada de recuperación transaccional; una confirmación parcial debe distinguirse del fallo total.

Verificado localmente: 372 pruebas frontend en 62 archivos, build y revisión cruzada. Navegador aislado a 390 y 1440 px: fallos 503 y recuperación de clientes, timer, registros de hoy, informes por cliente/proyecto y progreso; perfil sólo lectura sin controles de escritura, sin desbordamiento móvil. Las pruebas con QueryClient cubren 403→503→remontaje→reintento pendiente y recuperación fresca, además de invalidación entre observadores. Los 503 de consola son fallos inyectados sólo en la preview. Backend sin cambios desde P19 (1204 pruebas aprobadas y 2 omitidas); CI volverá a comprobarlo. Pendientes CI, publicación y verificación productiva.
