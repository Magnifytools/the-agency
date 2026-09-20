# Panel y resúmenes con fuentes y permisos claros

Estado: validada localmente; pendiente de CI y publicación. Producción continúa en P17.

El panel separa el resumen operativo de los importes financieros. Un miembro ve sus propias horas; las métricas cuyas fuentes no puede consultar quedan indisponibles, en lugar de aparecer como cero. El resumen del equipo exige administración y omite tarifas y costes cuando Finanzas está oculto. Las rutas financieras requieren administración, el módulo financiero y sus fuentes habilitadas.

El coste por persona usa minutos exactos y la misma tarifa predeterminada que los agregados cuando falta una tarifa personal; una tarifa explícita de cero se respeta. La capacidad configurada en cero se conserva y se presenta sin inventar porcentajes. Las alertas de clientes sin horas son de equipo y quedan reservadas a administración. El cierre mensual conserva la revisión de Holded, permite crear la primera fila concurrentemente sin perder parches y ya no escribe al abrir o exportar. La lectura de ajustes financieros tampoco crea registros.

El informe semanal de Discord usa hechos agrupados y períodos civiles coherentes. Separa las finalizaciones del período del trabajo pendiente actual, conserva horas históricas y distingue el total de tareas de la muestra mostrada. La versión operativa no consulta importes; el envío manual a administración añade el bloque financiero únicamente si Finanzas está habilitado. La capacidad actual se identifica como tal y no se mezcla con horas históricas de personas inactivas para producir un porcentaje global.

La vista previa diaria incluye fecha y revisión del texto. Al enviar, el servidor comprueba esa revisión antes de crear la entrega persistente. Si cambia el contenido, responde con conflicto y pide revisar de nuevo. Se conservan los recibos, la cola y la idempotencia existentes; una petición aceptada no se presenta como mensaje ya entregado.

Reports permanece oculto. La auditoría anterior a su ocultación registraba cero usos, mientras los resúmenes diarios, de clientes y Discord sí tenían consumidores. Se retiran los generadores duplicados y la analítica de demostración; sus rutas antiguas responden 410 y señalan Resúmenes de clientes. Los informes guardados permanecen en un archivo paginado con lectura, descarga y eliminación confirmada, respetando permisos de autor y administrador. No hay migración ni borrado de documentos históricos.

Validación local: suite integral backend de 1189 pruebas aprobadas y dos omitidas; la corrección posterior del coste pasa 66 pruebas dirigidas, incluida comparación contra ambos agregados financieros. Frontend: 337 pruebas y compilación correctas; Ruff y revisión de diferencias correctos. La página real cubre permisos, cambio de identidad y mes, errores 403→503→éxito y reintento retenido sin volver a mostrar datos revocados. Las alertas derivadas también dejan de usar datos cuya carga falla.

El navegador aislado verificó el archivo y su PDF como miembro de lectura, las cifras coherentes del administrador, el guardado del cierre de septiembre sin arrastrar notas a agosto y la vista previa diaria. El recibo local conserva exactamente el texto revisado, queda pendiente y tiene cero intentos de proveedor. Se inspeccionaron vistas a 390 y 1440 píxeles. Las escrituras sólo utilizaron datos sintéticos y no se enviaron comunicaciones a personas.

El objetivo global sigue abierto y mantiene los demás hallazgos de la auditoría.
