# Progreso

## 16 nov 2026
- Implementado en `feat/resumenes-saltar-periodo`: tabla + migración
  `digest_period_skips_v1`, servicio, API, avisos (`period_settled_clause`,
  `report_pending` en la misma lectura con `UNION ALL` para no pasar del
  presupuesto de 15 lecturas), estado del cliente, "Para entregar" (estado
  `skipped`; `preview_items` pasa de 4 a 5 lecturas, fijas) y front.
- Tests: unitarios backend 1243 OK; vitest 927 OK. Integración
  (`test_digest_period_skips*.py`) sin Postgres local: corre en el CI.
