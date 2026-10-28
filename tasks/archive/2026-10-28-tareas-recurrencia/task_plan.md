# Tareas y recurrencia (análisis Ruk Lab, 28 oct 2026)

Alcance elegido por David: recurrencia fiable, aviso de cronómetro olvidado y
subtareas en Mi agenda. Plantillas de tarea quedan para otra tanda.

## 1. Recurrencia fiable
- Reglas nuevas: `weekdays` (varios días L-V, columna `recurrence_weekdays`),
  `last_business_day` (último día hábil del mes, con festivos) y `quarterly`
  (día 1-28 cada tres meses desde el mes de la fecha de inicio).
- Festivos y fin de semana: una fecha que cae en día no hábil (sábado, domingo
  o festivo de quien lleva la plantilla; sin responsable, sólo nacionales) se
  crea el siguiente día hábil. La diaria se salta los festivos. La identidad
  (`recurrence_occurrence_date`) sigue siendo la fecha nominal.
- Recuperación: si el job no corrió algún día, crea las repeticiones de los
  últimos 7 días que no tengan recibo, nunca antes de `recurrence_since`
  (columna nueva: alta de la regla, cambio de regla o reanudar). Así una pausa
  no rellena las fechas pausadas.
- Migración versionada `task_recurrence_rules_v1`.
- Vista previa y resumen: próximas fechas ya movidas por festivos.

## 2. Cronómetro olvidado
- Incidencia `timer_running_long` para quien lo tiene en marcha: aviso a las
  4 h, crítica a las 8 h (hoy se recorta a 8 h en silencio). Se resuelve al parar.
- `POST /api/timer/stop` acepta `minutes` para corregir; la barra del
  cronómetro, pasadas 4 h, pregunta cuánto fue antes de parar.

## 3. Subtareas en Mi agenda
- Subtareas asignadas a mí, sin hacer y con fecha ≤ hoy (o sin fecha) de tareas
  abiertas que no llevo yo: sección propia en Mi agenda, marcar hecha y abrir
  la tarea.

## Verificación
pytest (unit + integración Postgres), vitest, tsc, navegador con BD aislada.
