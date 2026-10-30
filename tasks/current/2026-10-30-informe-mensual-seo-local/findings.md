# Hallazgos

- El paquete está en el scratchpad de la sesión (`paquete_david_informe/`):
  plantilla v6, referencia de octubre 2026 (1-26 oct, consultado el 28 oct).
- La plantilla sólo usa de `google`: periodo, vistas_perfil, interacciones,
  clics_llamada, indicaciones, clics_web, acciones_reserva, clics_carta,
  busquedas_que_mostraron_ficha y consultas. `comparativa_mensual` y
  `tecnico.estado_correccion` no se pintan: sirven a la redacción.
- Histórico de 16 meses de la referencia: 2025-06-29 → 2026-10-26 = hoy − 486
  días (`gsc_live.HISTORY_DAYS`) hasta el fin del periodo.
- Trimestre: del día 1 del mes de hace dos meses al fin del periodo
  (1 ago – 26 oct = 1.152; 2025: 853).
- Periodo parcial (1-26 oct): se compara con los mismos días del mes anterior y
  del año anterior. Serie mensual: 15 meses COMPLETOS (jul 2025 – sep 2026).
- Grupos: la tarjeta suma todas las consultas sin marca que casan con la
  familia `evento|celebra|comuni|bautiz|boda|empresa|grupo|navidad`, sin
  "karavan" (oct 7 clics/29 imp; sep 0/15). La tabla es una selección editorial.
- Tareas del plan: título `E<n> - <nombre>` (E1 = oct 2026). #1199 no tiene
  proyecto: se buscan por cliente, no sólo por el proyecto #18.
- Fuentes de la plantilla: Inter/Segoe UI/Arial y Georgia. En Debian slim no
  están: hacen falta fuentes en la imagen para que el PDF se parezca.
- Postgres local en :5432 (brew postgresql@16) para tests de integración.
