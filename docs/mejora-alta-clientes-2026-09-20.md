# Alta de clientes completa y recuperable

Estado: P21 publicada y verificada en producción. PR [33](https://github.com/Magnifytools/the-agency/pull/33), revisión `6f1c8ffe54b64b53ff369d8687bdf49afea7ba75`. El objetivo global continúa activo.

El formulario de Clientes prepara un alta que incluye el cliente, los contactos revisados y, si se ha incluido, su proyecto. El servidor confirma el conjunto en una sola transacción: un fallo no deja un cliente creado a medias ni descarta contactos silenciosamente. Las fechas ausentes se conservan vacías. Los sellos de creación y actualización nuevos de clientes, contactos y proyectos se guardan en UTC independientemente de la zona horaria de la sesión de base de datos; sus valores históricos se conservan.

Si se interrumpe la conexión, la aplicación comprueba el resultado antes de permitir repetir el alta. Un intento confirmado devuelve el mismo resultado; una cancelación confirmada impide que una petición retrasada lo cree después. La recuperación se mantiene al recargar y separa las cuentas. Sólo se conservan identificadores del intento en el navegador, sin copiar los datos del formulario.

Deshacer agrupa cliente, contactos y proyecto. Si después aparece trabajo que los referencia, se rechaza el cambio para conservarlo. Los contactos también quedan incluidos en el historial; su restauración respeta el contacto principal vigente y los permisos actuales. Un historial eliminado no se presenta como un alta deshecha. Los importes del historial se comparan y restauran con la misma escala y representación que guarda PostgreSQL; los recibos anteriores siguen siendo legibles y un cambio posterior real continúa bloqueando Deshacer.

La migración añade únicamente recibos de alta y cancelación. No rellena fechas ni modifica clientes, proyectos, contactos u horas existentes. Cada recibo conserva la clave del intento, su propietario, el resultado mínimo y la referencia a Deshacer; no almacena el contexto del cliente ni una copia de sus contactos.

La revisión permite corregir los datos de cada contacto y del proyecto detectado, excluirlos y elegir el contacto principal. Los campos avanzados se despliegan cuando hacen falta. Los errores de validación aparecen dentro del formulario y conservan lo escrito mientras se confirma que el intento no creó nada.

Límites explícitos: hasta 50 contactos por alta y como máximo uno marcado como principal. Crear un proyecto requiere su permiso de escritura además del de Clientes. El formulario debe permitir corregir los datos antes de enviarlos.

Verificación: 1.253 pruebas backend aprobadas (2 omitidas), 382 de frontend, `tsc -b` y build correctos. Las seis comprobaciones de CI pasan tanto en el último commit de la PR (`35537908243`) como en main (`35538255820`). Las pruebas PostgreSQL cubren concurrencia, rollback, permisos actuales, recuperación, migración y Deshacer.

El navegador aislado comprobó una respuesta perdida con una sola creación, recuperación del mismo resultado, edición persistida de contactos y proyecto, fechas vacías y Deshacer. Un conflicto inicial con importes decimales se reprodujo y corrigió antes de publicar: la repetición restaura tanto el recibo anterior como uno nuevo, manteniendo la protección frente a cambios posteriores reales.

Railway confirmó el despliegue `1ca6dd99-bdcc-4613-bdd7-975af05d92f2`; `/api/ready` devuelve la revisión publicada y el esquema `20260920_client_onboarding_v1`. Se verificaron listado y formulario a 390 y 1440 px, sin desbordamiento ni errores de consola. No se crearon clientes de prueba ni se enviaron comunicaciones en producción.

La comparación anterior/posterior conserva 955 tareas, 11 proyectos, 13 clientes, 15 contactos, 1.601 registros de tiempo, 112 dailys, 37 digests y 4 informes. Coinciden los hashes de clientes, contactos, proyectos, tareas, horas, notas e informes; el historial de migraciones conserva sus registros y añade únicamente la nueva versión. No existen recibos de altas de prueba en producción.

Siguiente entrega: coherencia del ciclo de trabajo, esperas, revisión y cierre de proyectos. La matriz de auditoría mantiene el resto de hallazgos y decisiones pendientes; P21 no cierra el objetivo completo.
