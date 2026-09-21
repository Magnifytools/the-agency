# Lecturas recuperables y fechas registradas

P25 validada localmente; publicación pendiente. Sin migración ni corrección automática de históricos.

Equipo, permisos, festivos, categorías y actividad distinguen carga, error y respuesta vacía. Un error oculta los datos retenidos y ofrece reintento. El editor de permisos no permite guardar una lectura fallida ni conserva los controles de otra persona. Si falla un catálogo mientras hay un borrado pendiente, la confirmación se cierra y la acción comprueba de nuevo la lectura válida.

El filtro de tareas atrasadas usa el día de negocio de Madrid. El calendario comienza en ese mes civil y conserva la navegación manual al actualizarse el reloj.

La actividad de cliente fecha las tareas completadas mediante `completed_at`. Las tareas históricas sin esa fecha se conservan, pero no se atribuyen a un día por su última edición. Hoy, Daily, Digest, actividad, burndown, ciclo mensual, semanal operativo y recap explican este límite. El progreso actual por estado y las horas históricas explícitas mantienen su significado.

Verificación local: 1.335 pruebas backend aprobadas y dos omitidas con PostgreSQL obligatorio; 425 pruebas frontend en 68 archivos; build TypeScript/Vite correcto. Las regresiones usan endpoints reales para fechas y QueryClient para errores con caché, cambio de identidad, reintento y recuperación de borrado. Navegador aislado, CI y producción pendientes.
