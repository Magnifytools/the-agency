# Proyecto y primera tarea desde una petición

Publicada mediante [PR23](https://github.com/Magnifytools/the-agency/pull/23), revisión `a2a21b5c75206ba991cf3c4c60700d194b465026`.

La captura global y la extensión permiten pedir un proyecto con su primera tarea. Se resuelven cliente, responsables y fechas, y se presenta el plan antes de guardar. La confirmación crea ambos elementos en una transacción; si falla uno, ninguno queda creado. Un recibo común permite deshacerlos respetando cambios posteriores. Si cambian los datos del plan antes de confirmar, se pide revisar la versión actualizada. Véase [el contrato de instrucciones](assisted-work.md).

También se pueden consultar decisiones pendientes. La respuesta reúne incidencias activas con enlaces a sus fuentes, respeta los permisos actuales y permite consultar el equipo a administradores. Las pospuestas reaparecen cuando el detector las reactiva. Consultar no resuelve incidencias ni genera un cambio para deshacer.

La interfaz protege respuestas tardías al editar o cambiar de petición. La vista de plantillas recurrentes muestra su propio contador y estados de carga, sin filtros de trabajo ordinario; la tabla mantiene columnas legibles con desplazamiento horizontal en móvil. La extensión 2.2.1 conserva su identidad de firma y muestra las decisiones en tarjetas legibles.

CI de rama `35512870196` y de main `35513062699` aprobadas: 997 pruebas backend, dos omitidas, 278 de interfaz y 46 de extensión. Seguridad, lint, build y contenedor correctos. PostgreSQL cubre atomicidad, concurrencia, permisos revocados, plan obsoleto, paginación superior a mil filas y Deshacer.

Los recorridos aislados comprobaron revisión sin escrituras, creación vinculada y Deshacer en la aplicación y en el popup con API real local. En este último se simularon las APIs de Chrome; no constituye una prueba de instalación MV3 de esta versión. La firma CRX3 y la equivalencia de los recursos empaquetados se comprobaron por separado.

Producción tiene la revisión exacta y superó 51 lecturas generales, seis colectores y las comprobaciones específicas de recurrencias y decisiones. La consulta de decisiones se ejecutó en una transacción de solo lectura, sin crear recibos. Los datos anteriores se conservaron y el paquete descargable coincide con el firmado: SHA-256 `93fb77a61aa8e31eb3d406c3df18ade4137ff68a3ca61ee484deb094e2b6e18b`. Plantillas y captura se revisaron visualmente a 390 y 1440 píxeles, sin errores de consola observados. No se modificó trabajo real ni se enviaron comunicaciones de prueba.

El objetivo completo sigue activo. Continúan el control de migraciones y procesos programados, la medición operativa, la revisión histórica y los demás criterios pendientes de la auditoría.
