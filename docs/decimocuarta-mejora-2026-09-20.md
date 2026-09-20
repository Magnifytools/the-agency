# Decimocuarta mejora: procesos programados fiables y visibles

Entrega validada localmente; publicación y comprobación productiva pendientes.

Los administradores disponen de un panel plegable en Ajustes para consultar los procesos programados, su última comprobación y sus fallos. No añade navegación principal ni activa módulos. Los ciclos se coordinan entre instancias, conservan su próxima fecha y recuperan ejecuciones interrumpidas. Los errores parciales dejan de aparentar un éxito global.

Las entregas mantienen sus leases y recibos independientes. La salud del worker no sustituye la confirmación del proveedor. Recurrencias y avisos conservan las identidades durables de sus ocurrencias. También se corrige el apagado de workers cuando uno ya ha fallado y el registro de uso del sondeo del cronómetro.

La migración añade únicamente `job_runtime` mediante un nuevo paso versionado. El contrato P12 permanece inmutable. El [runbook de procesos](procesos-programados.md) describe cadencias, configuración, recuperación y límites; el [runbook de esquema](schema-migrations.md) explica la publicación y compatibilidad entre revisiones.

Validación local:

- 1.067 pruebas de backend aprobadas, 2 omitidas; 282 de interfaz aprobadas. Pruebas dirigidas y build posteriores al ajuste visual final aprobados.
- PostgreSQL real: esquema vacío y actualización desde P13, repetición, drift, permisos, concurrencia, pérdida del lock, cancelación, reintento y cambio de hora.
- Proveedores sintéticos: errores parciales y observación de delivery sin repetir operaciones.
- Navegador a 390 y 1440 píxeles: panel real con estados pausados, ciclos correctos y fallo sintético saneado; sin desbordamiento horizontal. Recurrencias y reset avanzado ejecutados en la base aislada.
- Lectura productiva anterior al despliegue conserva revisión, datos y configuración. No se enviaron comunicaciones de prueba.

Continúa el objetivo global: Inbox fuera de estos loops, decisiones sobre módulos y canal, revisión histórica, escenarios de UX y medición de recorridos. Esta entrega no acredita por sí sola el cierre de toda la auditoría.
