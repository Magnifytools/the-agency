# Métricas Engine acotadas y verificables

Estado: preparada y verificada localmente el 20 de septiembre de 2026. Pendiente de integrar y publicar; la mejora vigente en producción sigue siendo P18.

Engine calcula ahora una instantánea por proyecto con dos períodos civiles consecutivos de 30 días. Suma clics e impresiones y pondera la posición por impresiones. El ranking usa la última observación de escritorio de cada palabra clave dentro del período actual y publica cuántas palabras tienen una observación reciente; una posición antigua ya no aparenta actividad actual.

El agregado vive en una función PostgreSQL acotada, estable y de sólo lectura. Su ejecución se reserva a `service_role`; las rutas `metrics`, `summary` y `alerts` validan primero la clave entre servicios y usan credenciales de servicio aunque la petición incluya una cookie o un JWT de usuario. Los errores de fuente dejan de convertirse en métricas saludables o ceros ficticios. `report-data` conserva por compatibilidad su implementación histórica y no forma parte de estas garantías; se revisará si se confirma un consumidor vigente.

La indexación distingue URLs inspeccionadas de URLs cuyo veredicto actual es `PASS`. La puntuación orientativa queda indisponible cuando faltan inspecciones o posición. Agency conserva la última instantánea completa: resumen y alertas se validan juntos, una respuesta parcial no sustituye la caché y un cambio concurrente de vínculo o estado impide escribir datos del proyecto anterior.

Vincular un cliente a Engine exige administración y comprueba que el proyecto existe antes de bloquear la fila del cliente. Cambiar o retirar el vínculo limpia los ocho campos cacheados. El sello de sincronización se guarda como un instante UTC en `TIMESTAMPTZ`; una prueba con sesión Europe/Madrid verifica que `18:59Z` vuelve a leerse exactamente como `18:59Z`.

Los productores GSC y GA4 conservan las columnas de la otra fuente mediante upsert parcial por contenido y fecha. Si falta la unicidad requerida, la importación falla sin reemplazar filas mediante borrado e inserción. Las cuatro migraciones Engine son aditivas respecto a los hechos: función, índices y mantenimiento medido de estadísticas y mapas de visibilidad; no reescriben el histórico.

Validación local: Engine aprobó 616 pruebas con PostgreSQL obligatorio. Seis pruebas PostgreSQL cubren 18.750 métricas y 3.600 observaciones; 42 pruebas cubren API e indexación. Los nueve handlers se recorrieron en modo de sólo lectura. En la comprobación final del proyecto de mayor volumen, `metrics` respondió en 2,407 s, `summary` en 1,762 s y `alerts` en 0,406 s. Agency aprobó 27 pruebas dirigidas de productor, contrato y PostgreSQL, incluidas sincronización correcta, fallos parciales, permisos y carreras de vínculo.

La interfaz aprueba 346 pruebas y el build. La revisión visual aislada a 390 y 1440 px verifica cobertura, indicador no disponible, permisos de administración y aviso de conexión ausente sin perder la caché. Engine PR7 está integrado tras CI aprobado; Agency continúa pendiente de CI y publicación. Esta entrega no afirma adopción humana ni completa el objetivo global de la auditoría.
