# Procesos programados

Los administradores pueden consultar **Ajustes → Procesos programados**. El panel se carga al abrirlo y se actualiza a petición. Muestra el último ciclo correcto, una ejecución en curso, interrupciones, fallos y pausas derivadas de la configuración. Los errores públicos son mensajes de catálogo; nunca se devuelven respuestas del proveedor, credenciales ni SQL.

“Comprobado” significa que terminó la revisión del proceso. Una entrega se confirma únicamente con su recibo. Las reglas recurrentes pausadas, los avisos bloqueados por su política y las conexiones personales se consultan en sus vistas correspondientes.

## Catálogo y coordinación

`backend/services/job_catalog.py` es el catálogo compartido por el arranque y la API administrativa. No hay una copia de las flags en base de datos.

| Proceso | Cadencia normal | Condición |
|---|---|---|
| Alertas accionables | 30 segundos | `INCIDENTS_ENABLED` |
| Entregas | Continua; 5 segundos sin trabajo | `DELIVERY_WORKER_ENABLED` |
| Engine | `ENGINE_SYNC_INTERVAL_HOURS` | Activado, URL y clave configuradas |
| Holded | 24 horas | Integración configurada |
| Reset de tareas avanzadas | 00:01, zona del negocio | Siempre; recuperación al arrancar |
| Recurrencias | 5 minutos | Siempre; sólo ocurrencias elegibles de hoy |
| Reglas de tareas vencidas | 00:01, zona del negocio | Módulo automatizaciones habilitado |
| Avisos programados | 1 minuto | `SCHEDULED_COMMUNICATIONS_ENABLED` |
| Calendar | 15 minutos | Google configurado y avisos habilitados |
| Retención | 24 horas | Siempre |

Cada barrido, salvo entregas, adquiere un advisory lock de sesión exclusivo por proceso y comprueba después su próxima fecha durable. La segunda instancia no repite un ciclo que acaba de terminar. Un heartbeat verifica que la misma conexión sigue manteniendo el lock; si lo pierde, cancela el trabajo. El cierre cancela todos los workers aunque uno haya fallado previamente y libera sus conexiones.

Al terminar se guardan el resultado y la próxima fecha con el reloj de PostgreSQL. Un fallo programa una nueva revisión en un máximo de 60 segundos; una caída deja el ciclo pendiente para recuperarlo. Las reglas de tareas vencidas esperan hasta las 00:01 en su primera activación, pero recuperan un ciclo existente interrumpido. Los horarios diarios contemplan los cambios de hora de la zona del negocio.

Los ciclos tienen un límite: cinco minutos por defecto, quince para Engine/Holded y diez para Calendar. El control SQL está acotado. La cancelación respeta la liberación de recursos de las operaciones; no puede deshacer una petición que un proveedor ya haya aceptado.

Entregas conserva sus leases, `SKIP LOCKED`, fencing y recibos de cada intento. Su observación de salud se escribe como máximo cada 30 segundos en ciclos correctos, e inmediatamente ante fallo del worker. Un error al guardar esta observación no vuelve a enviar contenido. Recurrencias y avisos conservan sus identidades de ocurrencia y sus transacciones de negocio.

## Resultados parciales y límites

Incidencias, Calendar, Holded, Engine y preparación de avisos terminan los elementos independientes y reportan fallo si alguno falla de forma inesperada. Los cambios confirmados no se revierten ni se presentan como un éxito global.

Holded conserva su integración configurada aunque su pantalla esté oculta. Ocultar una pantalla no equivale a apagar una dependencia ya utilizada. El monitor no activa capacidades ocultas ni crea programaciones.

El estado conserva el ciclo actual y el último éxito, no un historial ilimitado de cada sondeo. La retención existente sigue limitando los logs y conserva las incidencias canónicas. La clasificación de Inbox iniciada fuera de estos loops y la idempotencia completa de las automatizaciones heredadas siguen siendo asuntos separados; este panel no prueba su recuperación ni autoriza reactivarlas.

## Esquema y verificación

El paso aditivo `20260920_job_runtime_v1` crea `job_runtime`, sin cambiar filas de negocio. El plan vigente reside en `backend/startup/deployment_schema.py`; los artefactos publicados de P12 permanecen inmutables. La publicación ejecuta `python -m backend.scripts.migrate`; la aplicación sólo comprueba el resultado antes de arrancar los jobs.

La verificación cubre actualización desde P13, base vacía, repetición, drift, permisos administrativos, dos instancias, vencimientos, cancelación, pérdida de lock, timeout, cambio de hora y fallos parciales. La API de estado es sólo lectura y no ofrece acciones de ejecutar o reanudar.

## Medición de uso

`GET /api/timer/active` se excluye del registro de uso repetitivo. Iniciar, pausar, reanudar y detener conservan sus registros. Un GET no demuestra una acción humana y una petición de escritura no garantiza que haya cambiado datos. Los comandos mantienen su origen explícito en `CommandReceipt`; no se inventa retrospectivamente el canal de otras peticiones.

La métrica HTTP existente mide el handler y excluye el coste de guardar su propio registro. No debe presentarse como latencia completa del usuario. Los percentiles se ensayaron con datos sintéticos sin añadir un nuevo contrato sin consumidor; el rendimiento real de los recorridos continúa dentro de la verificación global de la auditoría.
