# Contrato temporal

La zona civil de negocio se configura con `AGENCY_TIMEZONE` y por defecto es
`Europe/Madrid`.

- Las fechas de planificación (`scheduled_date`, `due_date`, `start_date`) son
  fechas civiles `YYYY-MM-DD`. No se convierten a UTC.
- Los instantes (`completed_at`, `started_at`) se guardan como UTC naive por
  compatibilidad y se serializan con sufijo `Z`.
- `TimeEntry.date` conserva dos significados históricos. Una entrada manual
  (`started_at IS NULL`) contiene la fecha civil elegida. Una entrada de timer
  (`started_at IS NOT NULL`) contiene un instante UTC naive.
- Una entrada manual nueva sin fecha explícita usa `business_today()` a
  medianoche civil. Una fecha explícita se conserva; este criterio no rellena
  ni modifica entradas históricas.
- Los períodos civiles son semiabiertos: `[inicio, fin_exclusivo)`. El helper
  `time_entry_civil_period` aplica límites civiles a entradas manuales y límites
  UTC derivados de Madrid a timers. Los lectores no deben comparar ambas
  cohortes contra el mismo par de timestamps.
- Una semana se normaliza al lunes de la semana que contiene `week_start` y
  abarca siete días civiles completos, incluido el domingo.

No se migran ni se reinterpretan registros históricos ambiguos.

## Lectores de métricas

Los lectores activos de proyecto, presupuesto de timer, dashboard general,
dashboard de cliente, salud de cliente, notificaciones, digests y recap usan el
mismo helper. Los gráficos de tareas completadas convierten `completed_at` de
UTC a la fecha civil de negocio antes de agrupar.

Quedan fuera de este contrato los módulos ocultos de facturación y asesoría
(`backend/api/routes/billing.py` y `backend/services/client_advisor.py`). Sus
consultas históricas directas sobre `TimeEntry.date` deberán migrarse con el
mismo helper antes de volver a habilitar esos módulos. No se modifican datos
existentes para suplir procedencia desconocida.
