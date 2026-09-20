# Novena mejora — preparación local

Estado: implementación revisada; todavía no publicada. Producción conserva la octava entrega.

Hoy, la campana, el dashboard y la bandeja de alertas usan la misma incidencia y las mismas decisiones. Abrir un aviso no lo resuelve. Posponer requiere una fecha, descartar requiere un motivo y las acciones comprueban la revisión para evitar sobreescribir una decisión concurrente.

## Fuentes reales

- Tareas vencidas y esperas cuya fecha de seguimiento ha llegado.
- Proyectos con responsable explícito: sin próxima tarea planificada, cierre próximo o vencido y consumo de presupuesto de horas. Las tareas atrasadas cuentan como próximas acciones; las plantillas no. Los presupuestos usan tiempo registrado y el período correspondiente.
- Resúmenes pendientes para clientes con frecuencia y responsable configurados; el enlace conserva cliente y período.
- Entregas fallidas o inciertas, con enlace al recibo exacto y recuperación según permisos. Los resúmenes diarios, digests y comunicaciones manuales o programadas comparten esa cobertura.

Completar, reprogramar o corregir la fuente retira la condición de la lista actual y el detector conserva su resolución. Reasignar o borrar la fuente retira el acceso anterior, también del historial. Leer no reactiva un aviso. Las decisiones sobreviven al envejecimiento normal y a Deshacer dentro del mismo compromiso.

## Consolidación

El panel PM y el bloque de avisos independientes del dashboard se sustituyen por la bandeja compartida. El endpoint antiguo de comprobaciones delega a la reconciliación común. El generador antiguo de insights devuelve una respuesta de retirada; conserva los históricos. El resumen diario con IA sigue disponible. El dashboard también retira la generación masiva antigua, los recordatorios de resumen sin política y los banners personales que ignoraban la posposición. La lista de tareas vencidas del equipo conserva su función de consulta.

Se retiran las reglas que presumían obligaciones por falta de horas, dailys o actividad, y el job de facturación del módulo retirado. Los registros antiguos se conservan, pero sus condiciones obsoletas dejan de mostrarse como actividad. El historial de actividad y las incidencias pendientes mantienen significados separados.

## Integridad y despliegue

La migración es aditiva y no activa masivamente datos históricos. Registra la detección UTC sin reinterpretar fechas antiguas. La reconciliación serializa destinatarios y ordena los bloqueos de tareas; los escritores de permisos, las operaciones masivas y el reinicio de tareas avanzadas comparten el protocolo correspondiente. Las lecturas no escriben y comprueban los permisos y la fuente actual.

El detector permanece desactivado por defecto. Las pruebas de escritura se realizan con datos sintéticos, servicios externos desactivados y PostgreSQL aislado.

CI completa aprobada: 903 pruebas backend, dos omitidas y 238 pruebas de interfaz; extensión, seguridad y contenedor correctos. El último ajuste del dashboard pasa lint, TypeScript, tres pruebas dirigidas y build; queda su confirmación en la ejecución final de CI.

El recorrido aislado con API y PostgreSQL reales verifica detección sin sesión abierta, enlaces exactos, recibo incierto en móvil, preparación del período del aviso, retirada inmediata del contador y recuperación de un enlace antiguo sin generar otro período.

Pendiente: confirmación CI del último ajuste y despliegue. La proyección de incidencias a Discord queda para una entrega posterior con configuración explícita. Los resúmenes programados existentes son hechos y recordatorios con su propio consentimiento; no se infiere de ellos permiso para reenviar nuevas incidencias. Esta entrega no cierra la auditoría completa.
