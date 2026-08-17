# Progreso — fixes de la auditoría

Estado: **completado, sin desplegar**. Los cuatro fixes acordados están hechos y verificados en local.

## A. `None€` en las alertas — HECHO
- Extraído a `backend/services/profitability.py::format_billing_detail`.
- Un importe ausente ahora dice "sin importe configurado", no se finge como 0 €.
- Test: `backend/tests/test_alerts_billing_detail.py` (6 casos).

## B. "En riesgo" vs "sin tarifa" — HECHO (más grande de lo previsto)
- El mismo defecto estaba en DOS rutas, con síntomas distintos:
  - `dashboard.profitability` → cliente sin tarifa = "En riesgo".
  - `client_dashboard` → cliente sin tarifa = "No rentable" (umbral `< 10`).
- Lógica extraída a `classify_profitability()`, compartida por ambas. Los umbrales
  siguen siendo distintos por pantalla (20% vs 30%/10%) — se pasan por parámetro
  porque cambiarlos es decisión de producto, no de refactor.
- Nuevo estado `no_data` en el enum + tipo TS.
- **4 mapas de etiquetas** en el frontend unificados en `frontend/src/lib/profitability.ts`.
  Sin eso, `no_data` habría salido como "no_data" crudo en una pantalla y como
  "No rentable" en las otras tres.
- Tests: `test_profitability_status.py` (16 casos) + `profitability.test.ts` (6 casos).

## C. KPI del dashboard — HECHO (etiquetado, no cambio de query)
- "Tareas pendientes" → "Tareas del mes"; el tooltip dice explícitamente que las
  tareas sin fecha no se cuentan y remite a la página de Tareas.
- NO se tocó la query: el scope mensual es intencional (todo el dashboard es mensual).

## D. Higiene — PARCIAL, y el diagnóstico del informe era más amplio de lo real
- `npm audit fix`: de 12 vulnerabilidades (10 altas) a **0**. Solo cambió
  `package-lock.json`, ningún bump de semver en `package.json`.
- Lo de vitest: `output/` ya está en `.gitignore` y no está versionado, así que
  no es un defecto del repo — es scratch local de auditorías pasadas. El único
  spec suelto que SÍ está versionado en la raíz es `pw_smoke.spec.js`.
  **Pendiente de decisión de David**: borrarlo o moverlo a `frontend/e2e/`.

## Verificación
- Backend: **419 tests** en verde (397 baseline + 22 nuevos), 2 skipped.
- Frontend: **45 tests** en verde (39 baseline + 6 nuevos).
- `npx tsc --noEmit` limpio. `npm run build` OK.
- Contrastado el código viejo vs nuevo con los valores reales de producción:
  - Mosquita (0 € tarifa, 0 coste): `at_risk` → `no_data`
  - Taxfix (0 € tarifa, −56 € margen): `at_risk` / `unprofitable` → `no_data` en ambas
  - Sage (80,7%): `profitable` → `profitable` (sin regresión)
  - Detalle: `"Taxfix ES+UK: None€"` → `"Taxfix ES+UK: sin importe configurado"`

## Lo que NO se ha hecho
- **Desplegar.** Todo esto está en local, producción sigue con los bugs.
- El recorte de módulos muertos (~16.000 líneas) — fuera del alcance acordado.
- El N+1 de `GET /api/projects` (449 ms) — pendiente, era P1 en el informe.
- Notificaciones (284 sin leer), caducidad de alertas, estimaciones decorativas.

## Inconsistencia detectada de paso (no corregida)
Los umbrales de rentabilidad no coinciden entre pantallas: el dashboard llama
"Rentable" a partir del 20% y la ficha del cliente a partir del 30%. Un mismo
cliente al 25% sale "Rentable" en una pantalla y "En riesgo" en la otra.
Es una decisión de producto, por eso se ha preservado el comportamiento.
