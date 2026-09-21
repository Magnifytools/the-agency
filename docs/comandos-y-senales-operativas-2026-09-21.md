# Comandos comerciales y señales operativas

P26 está publicada y verificada en producción.

Una instrucción que intenta crear un proyecto con una tarifa, presupuesto, fee o importe no escribe un proyecto incompleto. Devuelve un recibo de derivación, conserva el texto original y abre el formulario vacío para revisar cliente, alcance y condiciones económicas. El recibo no anuncia entidades creadas y no ofrece Deshacer porque no hubo mutación. La gramática admite «crea proyecto», «crea un proyecto» y «crea el proyecto».

La app y la extensión declaran su origen mediante `X-Agency-Client`. El servidor acepta sólo `web` y `extension`; cualquier otro valor se registra como `unknown`. Este dato no participa en permisos y las filas históricas permanecen nulas. Los recibos de comandos e Inbox conservan sus canales propios.

Ajustes muestra al administrador seis señales pequeñas: contexto y planificación del trabajo actual, estados de incidencias, Dailys observados, resultado de comandos y confirmación de entregas. Cada bloque explica su población, período y denominador. Los estados pendientes quedan fuera de porcentajes terminales; una base ausente se muestra como insuficiente, no como 0 %. El origen de las peticiones se presenta aparte y se describe como volumen HTTP, no como personas ni acciones humanas.

La migración `20260921_usage_origin_v1` añade `audit_logs.client_origin VARCHAR(12) NULL` sin default ni backfill. La comprobación de preparación valida tipo, longitud, nulabilidad y ledger antes de servir tráfico.

Verificación: PR38, revisión `943ede244932a10825ad5e884edd4b9323b7569d`; CI de rama `35561547630` y de `main` `35562230448` con seis controles correctos; Railway `a87fcc21-afea-4499-b400-e6cc2c28805e` SUCCESS y readiness con la revisión/esquema exactos. La suite local aprobó 1.360 pruebas backend y dos omitidas con PostgreSQL obligatorio, 432 frontend y build, 48 de extensión y regresiones dirigidas de siete casos PostgreSQL y 28 de interfaz. El paquete 2.2.2 conserva la identidad `ocpnjmmpghndmfibgckajcapoejibhkk`; CRX3 firmado, ocho archivos iguales a fuente y SHA-256 `69ac0cb010e73bebb1accf9709c9dfbb167c4f372ff82a9e2491f991f0f87efe`.

El contrato productivo de sólo lectura comprobó esquema y ledger, cero orígenes inválidos, ACL 403 para miembro, denominadores internos y hashes del núcleo antes/después. La UI productiva mostró las seis señales sin alertas, errores de consola ni overflow a 1280 y 390 px. No se creó trabajo ni se envió ninguna comunicación de prueba.
