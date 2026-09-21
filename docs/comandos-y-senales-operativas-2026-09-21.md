# Comandos comerciales y señales operativas

P26 está validada localmente y pendiente de publicación.

Una instrucción que intenta crear un proyecto con una tarifa, presupuesto, fee o importe no escribe un proyecto incompleto. Devuelve un recibo de derivación, conserva el texto original y abre el formulario vacío para revisar cliente, alcance y condiciones económicas. El recibo no anuncia entidades creadas y no ofrece Deshacer porque no hubo mutación. La gramática admite «crea proyecto», «crea un proyecto» y «crea el proyecto».

La app y la extensión declaran su origen mediante `X-Agency-Client`. El servidor acepta sólo `web` y `extension`; cualquier otro valor se registra como `unknown`. Este dato no participa en permisos y las filas históricas permanecen nulas. Los recibos de comandos e Inbox conservan sus canales propios.

Ajustes muestra al administrador seis señales pequeñas: contexto y planificación del trabajo actual, estados de incidencias, Dailys observados, resultado de comandos y confirmación de entregas. Cada bloque explica su población, período y denominador. Los estados pendientes quedan fuera de porcentajes terminales; una base ausente se muestra como insuficiente, no como 0 %. El origen de las peticiones se presenta aparte y se describe como volumen HTTP, no como personas ni acciones humanas.

La migración `20260921_usage_origin_v1` añade `audit_logs.client_origin VARCHAR(12) NULL` sin default ni backfill. La comprobación de preparación valida tipo, longitud, nulabilidad y ledger antes de servir tráfico.

Verificación local hasta el freeze previo a publicación: 1.360 pruebas backend y dos omitidas con PostgreSQL obligatorio; 432 pruebas frontend y build; regresiones dirigidas de siete casos PostgreSQL y 28 de interfaz. El paquete de extensión 2.2.2 conserva la identidad `ocpnjmmpghndmfibgckajcapoejibhkk`; CRX3 firmado, ocho archivos iguales a fuente y SHA-256 `69ac0cb010e73bebb1accf9709c9dfbb167c4f372ff82a9e2491f991f0f87efe`. El E2E aislado comprobó derivación sin entidades, formulario vacío, seis señales, fallos independientes, ACL admin y 390/1440 px. CI, despliegue y producción se documentarán tras completarlos.
