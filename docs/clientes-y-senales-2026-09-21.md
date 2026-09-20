# Clientes y señales comprensibles

P24 está publicada y verificada en producción mediante PR36, revisión `bc900eef186083b59efe8d340c09e2c41946fccc`. No requiere migración.

Clientes permite combinar estado y tipo externo/interno. Los filtros se aplican en servidor antes del total y la paginación; la consulta de salud usa el mismo tipo y sólo evalúa clientes activos. La vista inicial se llama «En cartera» porque incluye activos y pausados; los finalizados tienen su filtro propio.

Las señales comprobadas tienen prioridad sobre la antigua puntuación. La interfaz distingue riesgos observados, información incompleta y ausencia de riesgos observados en las fuentes disponibles. Los clientes inactivos aparecen como no evaluados. Un fallo de consulta ofrece reintento y no se convierte en una valoración favorable.

Las observaciones explican sus ventanas: último contacto, tareas históricas y atrasadas actuales, resúmenes de cuatro semanas, presupuesto del mes civil y seguimientos vencidos. Dashboard identifica sus clientes como externos activos y separa esta foto actual del mes seleccionado. La ficha identifica clientes internos. No se cambia la población de informes semanales ni se reconstruyen datos históricos.

Verificación local final: 1.332 pruebas backend aprobadas y dos omitidas sobre PostgreSQL obligatorio; 416 pruebas frontend en 65 archivos; build TypeScript/Vite correcto. Las pruebas cubren filtros antes de paginar, fuentes ausentes, paridad individual/lote y recuperación de errores. La prueba antigua de coste mensual se actualizó al nuevo texto completo conservando su comprobación temporal. Navegador aislado con recuperación de errores y filtros, y producción a 1440/390 px comprobados: sin desbordamiento horizontal ni errores de consola. CI de PR `35544165884` y main `35544558563` correctos; Railway `49a25b57-ffb9-4a02-b28e-e7c12559416b` publicado. El contrato productivo hizo 29 lecturas: 13 clientes, nueve externos y cuatro internos, con poblaciones coherentes entre lista y salud. Los hashes, cantidades de entidades y ledger de esquema anteriores/posteriores se conservaron; no se escribieron datos reales para probar.
