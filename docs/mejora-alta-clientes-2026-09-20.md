# Alta de clientes completa y recuperable

Estado: implementación P21 en validación local. Producción continúa en P20 (`551eac8`).

El formulario de Clientes prepara un alta que incluye el cliente, los contactos revisados y, si se ha incluido, su proyecto. El servidor confirma el conjunto en una sola transacción: un fallo no deja un cliente creado a medias ni descarta contactos silenciosamente. Las fechas ausentes se conservan vacías. Los sellos de creación y actualización nuevos de clientes, contactos y proyectos se guardan en UTC independientemente de la zona horaria de la sesión de base de datos; sus valores históricos se conservan.

Si se interrumpe la conexión, la aplicación comprueba el resultado antes de permitir repetir el alta. Un intento confirmado devuelve el mismo resultado; una cancelación confirmada impide que una petición retrasada lo cree después. La recuperación se mantiene al recargar y separa las cuentas. Sólo se conservan identificadores del intento en el navegador, sin copiar los datos del formulario.

Deshacer agrupa cliente, contactos y proyecto. Si después aparece trabajo que los referencia, se rechaza el cambio para conservarlo. Los contactos también quedan incluidos en el historial; su restauración respeta el contacto principal vigente y los permisos actuales. Un historial eliminado no se presenta como un alta deshecha.

La migración añade únicamente recibos de alta y cancelación. No rellena fechas ni modifica clientes, proyectos, contactos u horas existentes. Cada recibo conserva la clave del intento, su propietario, el resultado mínimo y la referencia a Deshacer; no almacena el contexto del cliente ni una copia de sus contactos.

Límites explícitos: hasta 50 contactos por alta y como máximo uno marcado como principal. Crear un proyecto requiere su permiso de escritura además del de Clientes. El formulario debe permitir corregir los datos antes de enviarlos.

Verificación local: 1.243 pruebas backend aprobadas (2 omitidas), incluidas concurrencia, rollback, recuperación, permisos revocados, Deshacer y migración sobre el esquema anterior. Las 379 pruebas frontend pasan y el build final compila. La revisión del formulario permite excluir contactos y elegir expresamente que ninguno de los detectados sea principal.

Pendiente de publicación: terminar la comprobación del navegador aislado, CI, despliegue y preservación de producción.
