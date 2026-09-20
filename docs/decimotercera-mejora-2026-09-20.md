# Migraciones verificadas antes del arranque

Publicada mediante [PR24](https://github.com/Magnifytools/the-agency/pull/24), revisión `54d980292e37d4c22d857a80e1939128a9e928eb`.

La aplicación ya no intenta modificar el esquema al arrancar ni continúa tras omitir errores de DDL. Railway ejecuta primero una migración explícita. La web comprueba después la revisión y el contrato del esquema antes de iniciar procesos programados. Un fallo impide servir la nueva versión.

El ejecutor registra versiones y checksums, serializa actualizaciones concurrentes y mantiene cada paso en una transacción con tiempos de espera acotados. Admite una base vacía y predecesores comprobados mediante un artefacto congelado, independiente de cambios futuros del ORM. Conserva variantes históricas de tipos y valores por defecto; no ejecuta limpieza, seeds, atribuciones ni conversiones de datos. El antiguo grafo Alembic queda fuera del flujo de despliegue. Véase el [procedimiento de migraciones](schema-migrations.md).

El contrato comprueba columnas, tipos, longitudes, precisión, claves primarias, 95 relaciones y 30 reglas de unicidad por su significado. Se añadieron dos restricciones históricas ausentes después de comprobar que no había duplicados. Si aparecen conflictos, la migración falla sin elegir registros para borrar.

Validación: 38 pruebas PostgreSQL dirigidas y suite completa con 1.027 aprobadas y dos omitidas. CI de rama `35514848713` y de main `35515086615` aprobadas, incluyendo 278 pruebas de interfaz, 46 de extensión, seguridad, lint, build y contenedor. Se ensayó una copia y restauración real con datos sintéticos, comprobando contenido y revisión del esquema.

Producción registra los dos pasos y devuelve la revisión exacta junto con `schema_revision`. Las comprobaciones del contrato, las lecturas específicas, 51 lecturas generales y seis colectores pasaron. Las tareas conservaron su contenido y las versiones de los registros de cierres mensuales son anteriores a la migración. Hoy se revisó a 390 y 1440 píxeles, sin errores de consola observados. No se enviaron comunicaciones de prueba.

El objetivo completo sigue activo. Continúan el estado y recuperación de procesos programados, la medición operativa, los recorridos pendientes de UX y la revisión histórica.
