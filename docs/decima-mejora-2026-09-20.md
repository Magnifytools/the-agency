# Cierre diario con fuentes y borradores recuperables

Publicada mediante [PR21](https://github.com/Magnifytools/the-agency/pull/21), revisión `3d62a51afc53c5a3d4f0637753b45334b6ad4ae5`.

Guardar un resumen ya no espera a la IA. El editor conserva notas y fuentes por persona y fecha, compara versiones antes de resolver un conflicto y protege el texto escrito mientras llega una respuesta. El dashboard abre este mismo flujo para miembros y administradores.

Los hechos incluyen completados, avances, tiempo real, esperas y próximos pasos. Las fuentes conservan su versión histórica y los enlaces respetan los permisos actuales. Consultarlas o redactar notas no registra horas, completa tareas ni envía mensajes. La estructura opcional se aplica sólo a la revisión guardada correspondiente. Véase el [contrato del cierre diario](daily-closing.md).

Los resúmenes enviados o con recibos se conservan. La migración añade revisión, fuentes e índice único por persona/fecha; no fusiona duplicados ni reconstruye datos históricos. Los recibos anteriores mantienen su identidad. El despliegue pausó temporalmente el worker de entregas y lo reactivó tras verificar la nueva revisión; programación e incidencias permanecieron activas.

Verificación: CI de rama `35508427698` y de main `35508674663` aprobadas, con 929 pruebas backend, dos omitidas, 258 de interfaz y 42 de extensión. Seguridad, lint, build y contenedor correctos. Las pruebas PostgreSQL incluyen concurrencia, migración, revisión obsoleta, fuentes cambiantes y preservación de recibos.

El recorrido aislado en escritorio y móvil comprueba guardar, recargar, cambiar de fecha, estructurar y resolver un conflicto real sin perder notas. En producción se verificaron readiness, esquema, 51 lecturas API, seis colectores de informes y las pantallas de resumen/dashboard con datos cargados. Sin desbordamiento a 390 píxeles ni errores de consola observados. No se enviaron comunicaciones de prueba ni se modificó trabajo real.

El objetivo completo continúa con recurrencias explicables, cierre del ciclo mensual y el resto de la cobertura de la auditoría.
