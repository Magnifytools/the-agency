# Inbox recuperable y Hoy más claro

Estado: el primer despliegue se revirtió durante predeploy; producción conserva P14. Corrección de compatibilidad en verificación antes de publicar.

Las capturas se guardan antes de pedir una sugerencia. Un proceso recuperable revisa hasta cinco notas pendientes por ciclo; reiniciar la aplicación ya no pierde el trabajo pendiente. La IA sólo propone y nunca convierte una nota automáticamente. Si falla, la nota conserva su texto y muestra un reintento previsto, con opción de asignarla manualmente.

Las respuestas se aplican únicamente a la revisión original. Editar, asociar, descartar, convertir o borrar una nota invalida el resultado que estaba en curso. La clasificación vuelve a comprobar permisos y contexto; los nombres de las entidades se toman de los registros autorizados. Las asociaciones manuales exigen permisos y coherencia entre proyecto y cliente. Los campos de resolución se escriben únicamente mediante las acciones del dominio.

Inbox distingue carga, vacío y error, pagina el historial en grupos de 50 y separa la caché por persona y tipo de consulta. La vista Hoy conserva sus ámbitos personal/equipo y reduce el espacio de las alertas vacías. Las tareas completadas sin fecha registrada explican que no puede atribuirse su finalización a un día; no se rellenan fechas históricas.

El paso `20260920_inbox_recovery_v2` añade dos campos nullable y un índice parcial. No transforma notas históricas. El catálogo de Ajustes incorpora la clasificación. Los reintentos de Engine y Holded se espacian a 15 y 30 minutos respectivamente; esto reduce repeticiones costosas, pero no corrige por sí solo la consulta lenta de Engine, que sigue pendiente.

La verificación se realiza con notas y proveedores sintéticos en PostgreSQL aislado. Las comprobaciones productivas no crean notas, tareas ni comunicaciones de prueba.

Los adjuntos SVG, HTML y otros formatos activos siguen disponibles como descarga, sin ejecutarse dentro de la aplicación. Los nombres se codifican de forma segura y la lectura de subidas queda acotada.

Verificación local: 1.108 pruebas backend aprobadas (2 omitidas), 294 frontend, build y lint. Incluye actualización desde P14 sin alterar notas/ledger, rechazo de drift, carreras de clasificación/edición/conversión, revocación de permisos, reinicio, proveedor no configurado, lotes acotados sobre 50.000 notas históricas y adjuntos heredados. El navegador aislado verifica espera, error, reintento 202 y conversión manual 200 con proveedor sintético.

La corrección conserva el tipo de las fechas heredadas. El índice usa únicamente la fecha UTC del siguiente intento y una constante; la comprobación de revisión compara valores calculados dentro de PostgreSQL. Se prueban columnas `timestamp` y `timestamptz`, incluida una edición concurrente con sesiones en zonas horarias distintas. La revisión v1 fallida se conserva como evidencia y no forma parte del plan aplicado.
