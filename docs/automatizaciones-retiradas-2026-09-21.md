# Automatizaciones genéricas fuera del producto activo

El motor genérico de automatizaciones permanece oculto y detenido. La auditoría de uso encontró cero reglas ejecutadas en la ventana observada, y los casos que sí usa el equipo ya tienen procesos concretos con permisos, estado y recuperación propios. Reactivar el constructor genérico añadiría una segunda vía para modificar trabajo y enviar mensajes sin aportar un recorrido activo.

La configuración por defecto incluye `automations` en `HIDDEN_MODULES`. El catálogo presenta `overdue_automations` como pausado y `execute_automations` comprueba el mismo gate aunque se invoque directamente desde un hook. La regresión `backend/tests/integration/test_hidden_automation_gate.py` demuestra con PostgreSQL real que reglas activas heredadas no crean tareas, logs ni entregas y no realizan HTTP bajo esa configuración. Las filas históricas se conservan; esta decisión no las ejecuta, transforma ni elimina.

Una reactivación futura requiere antes un contrato revisado que:

1. identifique al actor efectivo y vuelva a comprobar sus permisos al ejecutar, sin atribuir reglas antiguas por inferencia;
2. registre esa autoría en el resultado durable de cada ejecución;
3. haga pasar cualquier efecto externo por el ledger `Delivery`, con outbox, lease, fencing, estado incierto y reenvío revisado, en lugar de HTTP inline;
4. reutilice los escritores comunes y sus locks para toda mutación de dominio;
5. pruebe revocación, doble worker, reinicio y fallo de base de datos tras una posible aceptación externa antes de cambiar el gate.

Hasta cumplir esos requisitos, el proceso permanece visible como pausado en el estado operativo y no se habilitan reglas, canales ni envíos de prueba.
