# Progreso — fixes de la auditoría

Estado: **DESPLEGADO Y VERIFICADO EN PRODUCCIÓN** (17 ago 2026, 04:01 UTC).
PR #1 mergeado por David; Railway desplegó en ~75 s.

## Verificado contra producción tras el deploy
- `GET /api/projects` → 449 ms → **19 ms** de tiempo de servidor (medido aislando
  solo las llamadas post-deploy contra `audit_logs`, no la media del día).
- Taxfix y Mosquita: `at_risk` → `no_data`. Sage/Kinetic/Fit Generation siguen
  `profitable` (sin regresión).
- Alertas: `"Taxfix ES+UK ...: None€"` → `"...: sin importe configurado"`.
- El listado de proyectos ya devuelve `monthly_fee` y `pricing_model`.

PR: https://github.com/Magnifytools/the-agency/pull/1 — 6 commits, 4 checks en verde.
Al mergear, Railway despliega. Producción corre `origin/main` = 4c0bb89 (17 jun).

## Hallazgo gordo del proceso de deploy
El PR #1 llevaba **8 semanas abierto sin poder mergearse** porque CI estaba rojo
**en la propia rama main**, por dos motivos independientes y pre-existentes:
  1. `ruff` marcaba 3 errores en `main` (uno de ellos un UnboundLocalError real
     que rompía la generación de briefs fiscales SIEMPRE).
  2. Los 23 tests de integración daban ERROR en vez de SKIP cuando no había
     Postgres, que es justo el caso de CI.
Ambos corregidos. Con eso, el PR pasa los 4 checks por primera vez.

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

## E. N+1 del listado de proyectos — HECHO (y más profundo de lo previsto)
- Contadores agregados con GROUP BY en vez de `len(p.tasks)` sobre un eager load.
- **Quitar el `selectinload()` no bastaba**: `lazy="selectin"` está declarado en el
  MODELO (en casi todas las relaciones de `models.py`), así que la carga ocurre
  igual. Hace falta `noload()` explícito. Lo destapó un test que cuenta queries;
  la suite unitaria no podía verlo porque mockea `get_db`.
- El mismo defecto estaba en `get_current_user`: `User.tasks` se cargaba en CADA
  petición autenticada de la app (75.000 al trimestre). Nadie lo lee — verificado
  en rutas y schemas. Desactivado.
- Medido con el test de integración: de 4 queries sobre `tasks` a 1, y esa con
  COUNT en vez de traerse las filas.
- El listado expone ya `monthly_fee` y `pricing_model`.

## Lo que NO se ha hecho
- **Mergear el PR** (bloqueado por permisos) y por tanto **desplegar**.
  Producción sigue con todos los bugs.
- **Medir la mejora real de latencia**: los 449 ms son de `audit_logs` en
  producción. Hasta que no se despliegue no hay número nuevo que enseñar.
- El recorte de módulos muertos (~16.000 líneas) — fuera del alcance acordado.
- Notificaciones (284 sin leer), caducidad de alertas, estimaciones decorativas.

## Deuda que he visto de paso y NO he tocado
- `lazy="selectin"` está en ~80 relaciones de `models.py`. Lo he desactivado en
  los dos sitios más calientes, pero el patrón afecta a toda la app y explica
  los 300-450 ms de casi todos los endpoints. Es un refactor grande y con riesgo:
  merece su propia tarea, no colarlo aquí.
- Los umbrales de rentabilidad no coinciden entre pantallas (20% vs 30%/10%).

## Inconsistencia detectada de paso (no corregida)
Los umbrales de rentabilidad no coinciden entre pantallas: el dashboard llama
"Rentable" a partir del 20% y la ficha del cliente a partir del 30%. Un mismo
cliente al 25% sale "Rentable" en una pantalla y "En riesgo" en la otra.
Es una decisión de producto, por eso se ha preservado el comportamiento.
