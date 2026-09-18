# Sexta entrega — 18 septiembre de 2026

Publicada en la [PR 17](https://github.com/Magnifytools/the-agency/pull/17), revisión `5f799f5`. El objetivo de mejora completa sigue activo.

Añadir permite escribir instrucciones para crear proyectos y tareas, completar, cambiar prioridad o fecha, registrar minutos explícitos y consultar prioridades. La app y la extensión conservan recibos, resuelven referencias ambiguas y permiten Deshacer cuando la operación admite una inversa segura. Los recibos muestran los datos realmente aplicados. Véase [instrucciones y límites](assisted-work.md).

Ajustes → Avisos permite configurar cada aviso, canal, antelación y horario de silencio. Las políticas requieren configuración explícita. La planificación y las entregas conservan estado durable; un resultado remoto incierto no se reenvía automáticamente. La sincronización de calendario pagina y reconcilia por usuario y calendario, preservando datos ante errores del proveedor. Véase [avisos programados](scheduled-communications.md).

Las tareas activas del cliente aparecen antes del historial de completadas, que queda plegado. Una ficha de proyecto eliminada o inaccesible deja de ofrecer acciones sobre datos obsoletos. La extensión 2.2.0 mantiene la identidad y firma existentes, incorpora instrucciones y utiliza el nuevo contrato de avisos.

Validación: 814 pruebas backend aprobadas y 2 omitidas, 167 frontend y 42 extensión; CI de rama y main, build, dependencias e imagen Linux correctos. Recorridos sintéticos verificaron creación, finalización, Deshacer, registro de minutos, políticas y extensión real. En producción se comprobaron esquema, readiness, 31 lecturas autenticadas, paquete firmado e interfaz de escritorio y móvil. Sin escrituras sintéticas ni mensajes de prueba en producción.

El despliegue detuvo los productores anteriores, esperó su retirada, migró y verificó la nueva revisión antes de activar el procesador y planificador nuevos. Continúan pendientes la política de informes por cliente, períodos y versiones, incidencias y otros escenarios de la auditoría. La siguiente entrega mejora también la explicación de autorizaciones de calendario que requieren reconexión y los enlaces directos a secciones de Ajustes.
