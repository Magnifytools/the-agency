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
- Los períodos civiles son semiabiertos: `[inicio, fin_exclusivo)`. El helper
  `time_entry_civil_period` aplica límites civiles a entradas manuales y límites
  UTC derivados de Madrid a timers. Los lectores no deben comparar ambas
  cohortes contra el mismo par de timestamps.
- Una semana se normaliza al lunes de la semana que contiene `week_start` y
  abarca siete días civiles completos, incluido el domingo.

No se migran ni se reinterpretan registros históricos ambiguos.
