# Fixes de la auditoría — 17 ago 2026

Origen: auditoría de código + producción de The Agency (ventana 2 jun – 17 ago 2026).
Alcance acordado con David: los 4 fixes rápidos. NO se toca el recorte de módulos muertos.

## A. `None€` literal en las alertas del dashboard
- Fichero: `backend/api/routes/dashboard.py:925`
- `"detail": [f"{p.name}: {p.billing_amount}€" ...]` sin guarda de `None`.
- El total dos líneas arriba sí protege (`float(p.billing_amount or 0)`).
- Fix: formatear el importe con la misma guarda + formato consistente (2 decimales).

## B. "En riesgo" significa a la vez "sin presupuesto" y "margen justo"
- Fichero: `backend/api/routes/dashboard.py:216-227`
- Dos defectos en la misma rama:
  1. `budget == 0` → `margin_pct` forzado a 0 → cae en `at_risk`. Mosquita (0 actividad) sale "En riesgo".
  2. Con `budget == 0` y coste real, el margen es NEGATIVO pero `margin_pct` = 0 esquiva `unprofitable`. Taxfix (margen −56 €) sale "En riesgo" en vez de "No rentable".
- Fix: nuevo estado `no_data` + el signo del margen manda sobre el porcentaje.
- OJO (lección Vigil): hay 3 mapas de etiquetas por estado en el frontend. Actualizar TODOS
  o el identificador crudo se cuela en pantalla:
  - `frontend/src/pages/dashboard-page.tsx:42` (tiene fallback, pintaría "no_data")
  - `frontend/src/pages/executive-dashboard-page.tsx:348` (ternario, pintaría rojo)
  - `frontend/src/lib/types/common.ts:86` (tipo)
- Verificar también si `client_dashboard` (profitability_status) comparte el bug.

## C. Los KPIs del dashboard esconden las tareas sin fecha
- Fichero: `backend/api/routes/dashboard.py:79-92`
- Los contadores filtran por `scheduled_date`/`due_date` dentro del mes.
- 23 de las 24 tareas en curso no tienen fecha → invisibles.
- Dashboard dice "1 en curso", la página de Tareas dice 22, la DB dice 24.
- Fix elegido: NO cambiar la query (el scope mensual es intencional y el dashboard es
  mensual de arriba abajo). Etiquetar los KPIs para que digan de qué hablan.

## D. Higiene
- `npm audit fix` en frontend (12 vulns, 10 altas; react-router-dom en prod).
- `vitest` desde la raíz arrastra specs de Playwright en `output/` → 6 ficheros rojos.
  Excluir `output/` en `vitest.config.ts`.

## Verificación exigida
- `pytest` backend en verde (397 tests baseline).
- `npx tsc --noEmit` limpio.
- `npm run test` frontend en verde (39 baseline).
- `vitest` desde la raíz ya no revienta.
- Comprobar A y B contra la respuesta real de producción antes/después.
