# Auditoría Pasada 5 - Código, Tests y UX (2026-02-26)

## Resumen Ejecutivo

Estado general: **estable en estático (lint/test/build)**, pero con **riesgos funcionales y de robustez** en áreas de finanzas/importación/UX móvil.

Lo más crítico detectado:

1. **Riesgo de corrupción de importes en CSV** por parser (`1234.56` se convierte en `123456.0`).
2. **Vulnerabilidad de CSV Formula Injection** en múltiples exports.
3. **Invalicación incorrecta de caché React Query en Holded** (`["holded"]` no invalida keys reales), causando UI estancada/stale.
4. **Fragilidad runtime del dashboard** (`insights.filter is not a function`) sin validación de shape.
5. **Arranque backend acoplado a DB + migraciones inline en startup** (observado: caída total cuando DB no accesible).

---

## Alcance y Metodología

Se revisó:

- Backend FastAPI (rutas, seguridad, manejo de errores, import/export, startup, RBAC).
- Frontend React (estado auth, React Query, rutas, UX responsive desktop/móvil, resiliencia de componentes).
- Pruebas automáticas existentes (unitarias frontend/backend, lint, build).
- Pruebas "vivas" de UX por navegador con rutas reales en desktop/móvil.

### Limitaciones del entorno

- El backend real no pudo levantarse contra su DB en este entorno por restricción de red/sandbox:
  - `PermissionError: [Errno 1] Operation not permitted` al conectar a PostgreSQL durante startup.
- Para ampliar validación UX autenticada, se usó un **mock API local temporal** (sin cambios en código de la app) para renderizar pantallas protegidas.

---

## Evidencia de Ejecución

### Calidad y tests

- `frontend npm run lint` -> **PASS**
- `frontend npm run test` -> **PASS (29/29)**
- `frontend npm run build` -> **PASS**
- `backend pytest -q` -> **PASS (9/9)**
- Warnings backend: deprecaciones Pydantic v2 (`class Config`)

### Cobertura (aproximada por estructura)

- Frontend: `92` archivos `src`, `3` archivos de tests.
- Backend: `108` archivos `.py`, `4` archivos de tests.

Conclusión: hay buen smoke base, pero cobertura insuficiente para rutas críticas nuevas (Holded, export, UX flows, errores de integración).

---

## Hallazgos Prioritarios (ordenados por severidad)

## P1 - Críticos/Altos

### 1) Corrupción de datos en importación CSV (parseo de importes)

- Impacto: financiero directo (importes mal guardados).
- Evidencia:
  - [`backend/services/csv_service.py:57`](../backend/services/csv_service.py#L57) - [`backend/services/csv_service.py:66`](../backend/services/csv_service.py#L66)
- Comportamiento observado en ejecución:
  - `parse_amount("1234.56") -> 123456.0` (incorrecto)
  - `parse_amount("1,234.56") -> 1.23456` (incorrecto)
- Causa: normalización agresiva `replace(".", "").replace(",", ".")` sin heurística de locale.
- Recomendación:
  - Detectar formato por regex/locale y no eliminar separadores indiscriminadamente.
  - Añadir tests parametrizados de parseo (`es_ES`, `en_US`, negativos, espacios, miles).

### 2) CSV Formula Injection en exports

- Impacto: seguridad al abrir CSV en Excel/Sheets (ejecución de fórmulas maliciosas en celdas de texto).
- Evidencia:
  - [`backend/api/routes/billing.py:85`](../backend/api/routes/billing.py#L85) - [`backend/api/routes/billing.py:88`](../backend/api/routes/billing.py#L88)
  - [`backend/api/routes/export.py:37`](../backend/api/routes/export.py#L37) - [`backend/api/routes/export.py:43`](../backend/api/routes/export.py#L43)
  - [`backend/api/routes/export.py:69`](../backend/api/routes/export.py#L69) - [`backend/api/routes/export.py:75`](../backend/api/routes/export.py#L75)
  - [`backend/api/routes/dashboard.py:388`](../backend/api/routes/dashboard.py#L388) - [`backend/api/routes/dashboard.py:391`](../backend/api/routes/dashboard.py#L391)
- Causa: campos de texto exportados sin neutralizar prefijos peligrosos (`=`, `+`, `-`, `@`).
- Recomendación:
  - Sanitizar celdas textuales prefijando `'` cuando empiecen por esos caracteres.
  - Test de seguridad de export.

### 3) Invalicación React Query defectuosa en Holded (stale UI)

- Impacto: tras sincronizar, la UI puede seguir mostrando datos antiguos o estados inconsistentes.
- Evidencia:
  - Invalidate incorrecto: [`frontend/src/pages/holded-finance-page.tsx:52`](../frontend/src/pages/holded-finance-page.tsx#L52), [`frontend/src/pages/holded-finance-page.tsx:506`](../frontend/src/pages/holded-finance-page.tsx#L506)
  - Keys reales distintas: `"holded-dashboard"`, `"holded-config"`, `"holded-invoices"`, `"holded-expenses"` en [`frontend/src/pages/holded-finance-page.tsx:120`](../frontend/src/pages/holded-finance-page.tsx#L120), [`frontend/src/pages/holded-finance-page.tsx:232`](../frontend/src/pages/holded-finance-page.tsx#L232), [`frontend/src/pages/holded-finance-page.tsx:369`](../frontend/src/pages/holded-finance-page.tsx#L369), [`frontend/src/pages/holded-finance-page.tsx:480`](../frontend/src/pages/holded-finance-page.tsx#L480)
- Causa: invalidar `queryKey: ["holded"]` no matchea keys que no comparten ese primer segmento exacto.
- Recomendación:
  - Invalidar keys explícitas o normalizar convención de keys (`["holded", "dashboard"]`, etc.).

### 4) Fragilidad runtime en Dashboard: crash por shape inesperado

- Impacto: pantalla completa de error boundary.
- Evidencia:
  - [`frontend/src/components/pm/insights-panel.tsx:82`](../frontend/src/components/pm/insights-panel.tsx#L82), [`frontend/src/components/pm/insights-panel.tsx:83`](../frontend/src/components/pm/insights-panel.tsx#L83)
- Error reproducido en vivo:
  - `insights.filter is not a function`
- Causa: se asume array sin guard (`Array.isArray`) si backend devuelve shape inesperado.
- Recomendación:
  - Validar shape en `queryFn` o en componente antes de usar `.filter`.

### 5) Arranque backend frágil por migraciones inline y dependencia dura de DB

- Impacto: disponibilidad total (si DB falla, app no arranca).
- Evidencia:
  - [`backend/main.py:30`](../backend/main.py#L30) - [`backend/main.py:33`](../backend/main.py#L33)
  - Gran bloque DDL/migraciones en startup: [`backend/main.py:33`](../backend/main.py#L33) - [`backend/main.py:173`](../backend/main.py#L173)
- Observado en ejecución real:
  - startup abortado por fallo de conexión DB.
- Recomendación:
  - Mover migraciones a Alembic exclusivamente.
  - Startup health no bloqueante (degradar, exponer estado, no matar proceso de inmediato).

---

## P2 - Medios

### 6) Validación insuficiente de `month/year` en export billing

- Impacto: respuestas 500 evitables por input inválido.
- Evidencia:
  - [`backend/api/routes/billing.py:20`](../backend/api/routes/billing.py#L20) - [`backend/api/routes/billing.py:25`](../backend/api/routes/billing.py#L25)
  - `month`/`year` sin límites en query: [`backend/api/routes/billing.py:31`](../backend/api/routes/billing.py#L31), [`backend/api/routes/billing.py:32`](../backend/api/routes/billing.py#L32)
- Recomendación:
  - Añadir `ge/le` en Query (`month 1..12`, year razonable) + manejo explícito de `ValueError`.

### 7) Manejo incompleto de errores en sync Holded

- Impacto: errores 500 y logs de sync inconsistentes.
- Evidencia:
  - Captura sólo `HoldedError` en syncs: [`backend/api/routes/holded.py:93`](../backend/api/routes/holded.py#L93), [`backend/api/routes/holded.py:192`](../backend/api/routes/holded.py#L192), [`backend/api/routes/holded.py:265`](../backend/api/routes/holded.py#L265)
  - `sync_all` sólo captura `HTTPException`: [`backend/api/routes/holded.py:281`](../backend/api/routes/holded.py#L281) - [`backend/api/routes/holded.py:285`](../backend/api/routes/holded.py#L285)
- Recomendación:
  - Capturar excepciones genéricas por cada etapa y registrar estado `error` consistente.

### 8) AppLayout consulta endpoint admin-only para todos los usuarios

- Impacto: para usuarios member, probable 403 + toasts innecesarios por layout global.
- Evidencia:
  - Query siempre activa en layout: [`frontend/src/components/layout/app-layout.tsx:15`](../frontend/src/components/layout/app-layout.tsx#L15) - [`frontend/src/components/layout/app-layout.tsx:20`](../frontend/src/components/layout/app-layout.tsx#L20)
  - Endpoint protegido por admin: [`backend/api/routes/holded.py:493`](../backend/api/routes/holded.py#L493) - [`backend/api/routes/holded.py:497`](../backend/api/routes/holded.py#L497)
- Recomendación:
  - `enabled: isAdmin` en query o endpoint de capabilities no-admin.

### 9) UX móvil: overflows y clipping (usuarios/holded/billing)

- Impacto: pérdida de información y acciones ocultas en móvil.
- Evidencia de código:
  - Tabla equipo sin layout móvil alternativo: [`frontend/src/pages/users-page.tsx:96`](../frontend/src/pages/users-page.tsx#L96)
  - Tabs Holded no adaptan bien en móvil: [`frontend/src/pages/holded-finance-page.tsx:92`](../frontend/src/pages/holded-finance-page.tsx#L92)
  - Cards métricas en 2 columnas fijas (números cortados): [`frontend/src/pages/holded-finance-page.tsx:139`](../frontend/src/pages/holded-finance-page.tsx#L139)
  - Header billing sin wrap (CTA fuera de viewport): [`frontend/src/pages/billing-page.tsx:41`](../frontend/src/pages/billing-page.tsx#L41)
- Evidencia visual:
  - `output/playwright/audit-2026-02-26/users-mobile-mockapi.png`
  - `output/playwright/audit-2026-02-26/holded-mobile-mockapi.png`
  - `output/playwright/audit-2026-02-26/billing-mobile-mockapi.png`

### 10) Mensajería de login no distingue credenciales vs caída de backend

- Impacto: diagnóstico erróneo para usuario final.
- Evidencia:
  - Siempre muestra `Credenciales incorrectas` en catch: [`frontend/src/pages/login.tsx:23`](../frontend/src/pages/login.tsx#L23) - [`frontend/src/pages/login.tsx:24`](../frontend/src/pages/login.tsx#L24)
- Recomendación:
  - Clasificar por status (`401` vs `>=500` vs network) y mostrar mensajes correctos.

### 11) Exposición potencial de detalle interno en errores HTTP

- Impacto: leakage de información interna.
- Evidencia:
  - [`backend/api/routes/pm.py:218`](../backend/api/routes/pm.py#L218)
  - [`backend/api/routes/reports.py:130`](../backend/api/routes/reports.py#L130)
  - [`backend/api/routes/proposals.py:459`](../backend/api/routes/proposals.py#L459)
  - [`backend/api/routes/holded.py:534`](../backend/api/routes/holded.py#L534)
- Recomendación:
  - Log interno completo + mensajes externos genéricos.

---

## P3 - Bajos / deuda técnica

### 12) Tokens JWT en `localStorage`

- Riesgo: ante XSS, exfiltración de sesión.
- Evidencia:
  - [`frontend/src/lib/api.ts:113`](../frontend/src/lib/api.ts#L113)
- Recomendación:
  - Migrar a cookie `HttpOnly` + CSRF.

### 13) API de invitaciones devuelve token en listados admin

- Riesgo: exposición innecesaria de token de alta de usuario.
- Evidencia:
  - [`backend/api/routes/invitations.py:30`](../backend/api/routes/invitations.py#L30)
  - [`backend/api/routes/invitations.py:49`](../backend/api/routes/invitations.py#L49)
- Recomendación:
  - Devolver token sólo al crear invitación o en endpoint específico con auditoría.

### 14) Rate limiter en memoria (no distribuido)

- Riesgo: inconsistencia en multi-worker/scale-out.
- Evidencia:
  - [`backend/core/rate_limiter.py:45`](../backend/core/rate_limiter.py#L45)
- Recomendación:
  - Redis o storage compartido para límites de login/IA.

### 15) Warnings Pydantic v2 (`class Config`)

- Evidencia:
  - [`backend/schemas/alert_settings.py:26`](../backend/schemas/alert_settings.py#L26)
  - [`backend/schemas/proposal.py:44`](../backend/schemas/proposal.py#L44)
  - [`backend/schemas/proposal.py:169`](../backend/schemas/proposal.py#L169)
- Recomendación:
  - Migrar a `model_config = {"from_attributes": True}` para evitar deuda de upgrade.

### 16) Endpoints Holded list sin `response_model` (bloat/shape drift)

- Impacto: payloads grandes/no estables (incluyen potencialmente `raw_data`).
- Evidencia:
  - [`backend/api/routes/holded.py:329`](../backend/api/routes/holded.py#L329)
  - [`backend/api/routes/holded.py:373`](../backend/api/routes/holded.py#L373)
- Recomendación:
  - Tipar explícitamente respuesta paginada y excluir `raw_data` del payload público.

---

## Hallazgos UX (Live)

### Desktop

- Login correcto visualmente.
- Users / Holded / Billing renderizan bien con API válida.

### Móvil

- **Users**: clipping de columnas y edición fuera de vista.
- **Holded**: tabs y métricas cortadas; scroll horizontal no intencional.
- **Billing**: vista previa y header no priorizan CTA en ancho pequeño.

Capturas:

- `output/playwright/audit-2026-02-26/login-desktop.png`
- `output/playwright/audit-2026-02-26/login-mobile.png`
- `output/playwright/audit-2026-02-26/users-desktop-mockapi.png`
- `output/playwright/audit-2026-02-26/users-mobile-mockapi.png`
- `output/playwright/audit-2026-02-26/holded-desktop-mockapi.png`
- `output/playwright/audit-2026-02-26/holded-mobile-mockapi.png`
- `output/playwright/audit-2026-02-26/billing-desktop-mockapi.png`
- `output/playwright/audit-2026-02-26/billing-mobile-mockapi.png`
- Estado token inválido (toast + redirección login):
  - `output/playwright/audit-2026-02-26/dashboard-with-invalid-token-desktop.png`
  - `output/playwright/audit-2026-02-26/dashboard-with-invalid-token-mobile.png`

---

## Matriz de Riesgo

| ID | Área | Tipo | Severidad | Probabilidad | Impacto |
|---|---|---|---|---|---|
| R1 | CSV import | Integridad datos | Alta | Alta | Alto |
| R2 | CSV export | Seguridad | Alta | Media | Alto |
| R3 | Holded cache invalidation | Funcional | Alta | Alta | Medio-Alto |
| R4 | Dashboard insights shape | Robustez UX | Alta | Media | Alto |
| R5 | Startup DB acoplado | Disponibilidad | Alta | Media | Alto |
| R6 | Mobile overflow | UX | Media | Alta | Medio |
| R7 | Error details leaked | Seguridad info | Media | Media | Medio |
| R8 | localStorage token | Seguridad sesión | Media | Media | Medio |

---

## Plan de Acción Recomendado

### Fase 1 (24-48h)

1. Corregir `parse_amount` + tests de regresión multi-locale.
2. Arreglar invalidación React Query en Holded.
3. Sanitizar exports CSV contra fórmula.
4. Guardas de shape (`Array.isArray`) en `InsightsPanel`.

### Fase 2 (Sprint corto)

1. Refactor startup DB (quitar migraciones inline de `main.py`).
2. Endurecer manejo de errores (sin exponer `str(e)` al cliente).
3. Añadir validaciones `month/year` en rutas export.
4. Ajustar UX móvil de Users/Holded/Billing con layouts responsive reales.

### Fase 3 (hardening)

1. Revisar modelo de sesión (`HttpOnly cookie + CSRF`).
2. Rate limit distribuido (Redis).
3. Expandir suite E2E y contract tests para rutas críticas.

---

## Estado Final de esta pasada

- No se modificó código de aplicación.
- Se ejecutó auditoría técnica profunda (código + pruebas + UX vivo).
- Se generó evidencia visual y recomendaciones accionables priorizadas.

MD generado en:

- `docs/auditoria-pasada5-codigo-tests-ux-2026-02-26.md`

