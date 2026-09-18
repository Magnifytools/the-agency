# Quinta entrega — 18 septiembre de 2026

Publicada en la [PR 16](https://github.com/Magnifytools/the-agency/pull/16), revisión `1375eca`. El objetivo de mejora completa sigue activo.

La ficha de cliente organiza sus vistas en Resumen, Trabajo, Resúmenes y archivos y Ajustes. Mantiene los enlaces anteriores y los permisos; muestra el trabajo antes de las métricas. Las tareas tienen una disposición legible en móvil y cada pestaña gestiona sus propias cargas y errores.

Los envíos manuales de briefing, resumen diario, informe semanal y texto personalizado guardan intención y recibo durables. Se conserva el texto exacto, período, destino y resultado por parte. Un envío incierto requiere revisión para reenviar. El briefing permite ver fecha y texto antes de compartir; cerrar la vista previa no oculta el historial de entregas. Véase [comunicaciones manuales](manual-communications.md).

Los servicios de creación y edición se comparten entre las entradas existentes. El historial de Deshacer se confirma en la misma transacción que el cambio. La inversa protege ediciones y trabajo añadido después, bloquea las filas mientras comprueba conflictos y diferencia restauración completa, parcial o ninguna. Véase [contrato de Deshacer](undo-transactions.md).

Validación: 760 pruebas backend aprobadas y 2 omitidas, 149 frontend, 31 extensión; build, auditoría de dependencias e imagen Linux correctos. CI de rama y main aprobado. Recorridos con datos sintéticos comprobaron escritorio y móvil, recibos y creación seguida de Deshacer. En producción se verificaron readiness, esquema, 26 lecturas autenticadas e interfaz a 1440 y 390 píxeles, sin escrituras de prueba ni mensajes externos de prueba.

El despliegue pausó el procesador anterior, retiró sus procesos, migró y verificó la nueva revisión antes de reactivarlo. Se incluye un [control de pausa de productores antiguos](scheduled-rollout-bridge.md) para la siguiente migración.

Los avisos programados configurables y las órdenes desde app/extensión se integran en la siguiente entrega. También continúa la revisión de incidencias, resúmenes, recurrencias y los escenarios de la auditoría; esta publicación no declara cerrado el objetivo completo.
