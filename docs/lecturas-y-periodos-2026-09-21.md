# Lecturas recuperables y fechas registradas

P25 está publicada y verificada en producción mediante PR37, revisión `8596bfb2db89b867ca7ab9fc34a64e54622716d0`. Sin migración ni corrección automática de históricos.

Equipo, permisos, festivos, categorías y actividad distinguen carga, error y respuesta vacía. Un error oculta los datos retenidos y ofrece reintento. El editor de permisos no permite guardar una lectura fallida ni conserva los controles de otra persona. Si falla un catálogo mientras hay un borrado pendiente, la confirmación se cierra y la acción comprueba de nuevo la lectura válida.

El filtro de tareas atrasadas usa el día de negocio de Madrid. El calendario comienza en ese mes civil y conserva la navegación manual al actualizarse el reloj.

La actividad de cliente fecha las tareas completadas mediante `completed_at`. Las tareas históricas sin esa fecha se conservan, pero no se atribuyen a un día por su última edición. Hoy, Daily, Digest, actividad, burndown, ciclo mensual, semanal operativo y recap explican este límite. El progreso actual por estado y las horas históricas explícitas mantienen su significado.

Verificación: 1.335 pruebas backend aprobadas y dos omitidas con PostgreSQL obligatorio antes del ajuste final de permisos; 54 pruebas dirigidas posteriores; 425 pruebas frontend en 68 archivos y build TypeScript/Vite. CI de PR `35545348123` y main `35559709495`, ambos con seis gates correctos; Railway `fa23a0cd-3cbb-43cf-b2d9-dc6cb5d09519` publicado. El navegador aislado cubrió errores, cambio de identidad y recuperación a 390/1440 px. En producción, 16 lecturas verificaron dos usuarios, la denegación de un miembro, trece actividades de cliente y 41 finalizaciones fechadas exactamente con `completed_at`. Las 898 finalizaciones antiguas sin fecha permanecen excluidas, sin atribución inventada.

La comprobación de preservación mostró un cambio de cliente anterior al despliegue, coincidente con la ejecución programada de Engine entre las dos capturas. Dos capturas consecutivas posteriores al despliegue conservaron todos los hashes, cantidades y el ledger; tareas, proyectos, horas, informes, contactos y recibos permanecieron iguales. No se escribieron datos reales durante la verificación.
