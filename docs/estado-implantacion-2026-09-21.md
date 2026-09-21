# Estado de la mejora de The Agency · 21 de septiembre de 2026

La auditoría privada de septiembre identificó tareas, horas y resúmenes como núcleo real; la navegación, los proyectos y algunas señales no reflejaban ese trabajo con fiabilidad. Las entregas P1–P29 ya están integradas y publicadas en `agency.magnifytools.com`. Esta nota distingue la implementación comprobada de la aceptación con personas y servicios externos. El informe y sus muestras viven en el espacio privado de trabajo, no en este repositorio publicado.

## Qué se puede usar ahora

- Cinco áreas: Hoy, Trabajo, Clientes, Resúmenes y Ajustes. Añadir, buscar y cronómetro permanecen accesibles globalmente. Trabajo reúne tareas, proyectos y horas; las vistas de equipo dependen de permisos.
- Un alta de cliente con contactos y proyecto opcional es atómica y recuperable; proyecto y primera tarea admiten instrucciones revisables. La app y la extensión autenticada permiten capturar, crear, completar, reprogramar, registrar tiempo explícito y consultar prioridades con confirmación, permisos, recibo y Deshacer cuando corresponde.
- Las tareas distinguen planificado, atrasado, espera, revisión y cierre sin trasladar automáticamente los atrasos a hoy. Los proyectos tienen siguiente acción, revisión de cierre y archivo. El histórico no se reasignó a proyectos ni recibió fechas de finalización inventadas.
- Los avisos internos agrupan condiciones reales por destinatario y decisión, con preferencias y entregas durables. Daily e informes usan períodos coherentes, hechos disponibles y borradores/versiones recuperables; los informes generados enlazan sus afirmaciones a fuentes verificadas cuando existen. El total de horas se cita como agregado, no como cada entrada individual.
- La interfaz de las rutas activas se revisó en móvil y escritorio: contraste y nombres de controles corregidos, estados vacíos válidos, mensajes de recuperación y vocabulario claro. Esto no certifica cumplimiento universal de accesibilidad.

Los módulos antiguos de CRM, finanzas, propuestas y automatización genérica siguen ocultos porque no hay evidencia actual para convertirlos en el recorrido principal. Sus datos se conservan. Los avisos de deuda inferidos por fecha permanecen desactivados hasta que exista una fuente fiable de facturas y cobros.

## Evidencia técnica de la última entrega

- PR [#41](https://github.com/Magnifytools/the-agency/pull/41), `main` `3d48fea239bca69f33e219fddbe4008c5005ae3e`; [CI de rama](https://github.com/Magnifytools/the-agency/actions/runs/35571202754) y [CI de main](https://github.com/Magnifytools/the-agency/actions/runs/35571775750): seis controles correctos cada uno, incluidos backend, frontend, extensión, contenedor y seguridad configurada.
- Railway `03c5bcc0-306e-4ab3-95b8-e8840dc380be` SUCCESS. `/api/ready` comunicó la revisión exacta y esquema `20260921_usage_origin_v1`.
- Comparación productiva de solo lectura: 13 clientes, 11 proyectos, 957 tareas, 1601 entradas de tiempo, 112 cierres diarios, 37 informes de cliente y 4 informes archivados. Los siete hashes fueron idénticos antes y después de P29 y frente a P28. Las lecturas de informe respetaron permisos de administrador/miembro y no expusieron metadata interna.
- Barrido de 13 rutas activas y detalles/altas a 390 y 1440 píxeles; Horas, Visión general y ficha de cliente comprobadas en producción sin desbordamiento horizontal ni errores de consola. Los recorridos de escritura se verificaron con base sintética aislada, sin modificar trabajo real ni enviar mensajes de prueba.

## Lo que falta comprobar con David y Nacho

Una sesión breve con trabajo real debe observar, por persona, alta de proyecto y primera tarea, completar una tarea, capturar una petición ambigua, registrar/corregir horas, cerrar el día y decidir una excepción. Anotar dispositivo, tiempo, confusiones y resultado; las referencias de menos de dos minutos para alta/daily, diez segundos para completar y cinco minutos para una decisión son objetivos, **no medidas obtenidas**. No crear entidades ficticias en producción sólo para esta prueba.

La lectura de producción del 21 de septiembre confirmó que **las dos cuentas activas** conservan una credencial de Google Calendar, pero están marcadas como desconectadas y sin última sincronización. Cada propietario debe abrir Ajustes → Calendar, pulsar «Reconectar Google Calendar», completar el consentimiento, elegir «Sincronizar ahora» y comprobar una reunión propia en Hoy. Hasta entonces no se debe dar por fresca la agenda ni los avisos asociados.

El motor de comunicaciones está habilitado, pero no existe política semanal activada ni ocurrencia o recibo semanal en producción. Para comprobar una entrega ordinaria, David debe decidir primero si desea ese informe y confirmar el destinatario de Discord, activar la política explícita en Ajustes y observar un recibo real `sent` con identificadores de mensaje. No se ha enviado un mensaje sintético. Los avisos financieros requieren acordar la fuente de deuda y el responsable operativo antes de implementarse. App y extensión son el canal de comandos ya disponible; un bot entrante o voz integrada sólo se justifican si el uso real demuestra una fricción concreta y una identidad verificable. Las propuestas de corrección histórica necesitan revisión de las muestras originales por sus propietarios.

La matriz detallada de hallazgos, límites y propuestas históricas permanece en `tasks/current/2026-09-17-implementacion-completa/coverage.md` del espacio privado de trabajo. El objetivo global continúa activo hasta registrar estas comprobaciones o decisiones.
