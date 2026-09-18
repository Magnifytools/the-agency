# Deshacer y confirmación del cambio

Los cambios operativos capturados y su entrada de `change_logs` se guardan en la misma transacción. No hay una tarea asíncrona que pueda perder el historial después de responder. Un error al guardar el journal hace fallar el commit del cambio; el caller revierte la transacción.

La captura sigue usando el historial ORM existente: una acción agrupa sus operaciones, conserva el valor original al editar varias veces y respeta los SAVEPOINT. Deshacer vuelve a comprobar permisos, propiedad del cambio y conflictos con ediciones posteriores. Un rollback o el cierre de la sesión descarta tanto el cambio como su entrada provisional.

`change_journal.prepare_entry(session)` permite obtener el ID provisional para asociarlo a un recibo dentro de la misma transacción. Es idempotente; el commit exterior actualiza el contenido si hubo más cambios. No confirma la transacción y no puede invocarse dentro de un SAVEPOINT. Un adaptador que prometa Deshacer debe exigir una entrada válida antes de confirmar su operación.

Se conserva el alcance anterior: entidades operativas del journal, exclusión de SQL masivo y módulos financieros, y límite de 300 operaciones por entrada. Los temporizadores no generan por sí solos una restauración del total derivado; las ediciones explícitas de tiempo que se agrupan deben activar la captura correspondiente. No se reconstruye historial ausente ni se atribuyen acciones pasadas.

Readiness comprueba las columnas del journal. Las pruebas PostgreSQL leen entradas reales y cubren permisos, conflictos, horas, fallos de almacenamiento, rollback, preparación repetida, SAVEPOINT y sesiones independientes. Los comandos naturales todavía requieren su adaptador y recibos; esta entrega prepara su garantía transaccional.

Los checkpoints usan los eventos públicos `after_transaction_create` y `after_soft_rollback`: restauran la longitud de la captura y el indicador de tiempo manual al revertir un SAVEPOINT. `after_transaction_end` descarta el estado al cerrar la transacción raíz, incluso al reutilizar una sesión. Véase [eventos de SQLAlchemy](https://docs.sqlalchemy.org/en/20/orm/events.html#sqlalchemy.orm.SessionEvents.after_soft_rollback).
