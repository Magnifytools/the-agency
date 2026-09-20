# Clientes y señales comprensibles

P24 está validada localmente y pendiente de publicación. No requiere migración.

Clientes permite combinar estado y tipo externo/interno. Los filtros se aplican en servidor antes del total y la paginación; la consulta de salud usa el mismo tipo y sólo evalúa clientes activos. La vista inicial se llama «En cartera» porque incluye activos y pausados; los finalizados tienen su filtro propio.

Las señales comprobadas tienen prioridad sobre la antigua puntuación. La interfaz distingue riesgos observados, información incompleta y ausencia de riesgos observados en las fuentes disponibles. Los clientes inactivos aparecen como no evaluados. Un fallo de consulta ofrece reintento y no se convierte en una valoración favorable.

Las observaciones explican sus ventanas: último contacto, tareas históricas y atrasadas actuales, resúmenes de cuatro semanas, presupuesto del mes civil y seguimientos vencidos. Dashboard identifica sus clientes como externos activos y separa esta foto actual del mes seleccionado. La ficha identifica clientes internos. No se cambia la población de informes semanales ni se reconstruyen datos históricos.

Verificación local final: 1.332 pruebas backend aprobadas y dos omitidas sobre PostgreSQL obligatorio; 416 pruebas frontend en 65 archivos; build TypeScript/Vite correcto. Las pruebas cubren filtros antes de paginar, fuentes ausentes, paridad individual/lote y recuperación de errores. La prueba antigua de coste mensual se actualizó al nuevo texto completo conservando su comprobación temporal. Navegador aislado, CI y producción se documentarán tras comprobarlos.
