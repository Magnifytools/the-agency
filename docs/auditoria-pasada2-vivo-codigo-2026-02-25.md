# Auditoría Profunda The-Agency (Pasada 2 + Revalidación en Vivo)

Fecha: 2026-02-25  
Proyecto: `the-agency`  
Tipo: Auditoría combinada (código + ejecución en vivo desktop/móvil)  
Estado: Finalizado

## 0) Nota de validez de entorno (importante)

Durante esta pasada hubo dos etapas de ejecución viva:

1. **Cobertura funcional completa (24/24 rutas desktop y 24/24 móvil)** con artefactos `v5`/`v6`.
2. **Revalidación en caliente contra el backend correcto de `the-agency`** para confirmar hallazgos críticos.

Detalle de control:

- El frontend de `the-agency` proxya `/api` a `localhost:8004` (`frontend/vite.config.ts:15-17`), y al inicio de la sesión ese puerto estaba servido por otro backend activo en el equipo.
- Por ese motivo, se realizó una **revalidación adicional explícita** levantando `backend.main:app` de `the-agency` en `:8004` y reproduciendo de nuevo seguridad + errores críticos + smoke visual desktop/móvil.
- Los hallazgos críticos de este informe están marcados como **confirmados en revalidación backend-correcto**.

## 1) Resumen ejecutivo

Riesgo global actual: **CRÍTICO**.

Bloqueadores principales antes de producción:

1. **JWT comprometible**: clave por defecto utilizable para forjar tokens y aceptación de token sin `exp`.
2. **Crash de dashboard (desktop y móvil)** por desalineación de tipos de insight (`quality`) que rompe render en `InsightCard`.
3. **Timesheet 500** por mezcla `datetime` naive/aware.
4. **Holded 500** en dashboard/facturas/gastos por fallo de validación de schema.
5. **Integraciones no resilientes** (`discord`/`digests`) con 500 sin manejo robusto.

Conteo de severidad (esta pasada consolidada):

- Critical: 1
- High: 5
- Medium: 4
- Low: 2

## 2) Alcance y metodología

### 2.1 Revisión de código

Revisión estática de backend y frontend, incluyendo auth, permisos, rutas críticas y capas de integración externa.

### 2.2 Pruebas vivas full-pass (cobertura total)

- Desktop: 24/24 rutas
- Móvil: 24/24 rutas
- Se registraron clics por ruta, fallos de clic, eventos de consola y errores HTTP.

### 2.3 Revalidación backend-correcto (segunda pasada viva)

Se ejecutó una batería adicional para eliminar ambigüedad de entorno:

- API recheck: auth/JWT, RBAC, timesheet, holded, discord, digests.
- Smoke visual desktop/móvil: `/dashboard` y `/finance-holded`.

### 2.4 Artefactos de evidencia

- Full-pass Desktop summary: `/Users/david/Public/Código/the-agency/output/playwright/deep-pass-2026-02-25-v5/desktop-summary.json`
- Full-pass Desktop trace: `/Users/david/Public/Código/the-agency/output/playwright/deep-pass-2026-02-25-v5/desktop-trace.zip`
- Full-pass Mobile summary: `/Users/david/Public/Código/the-agency/output/playwright/deep-pass-2026-02-25-v6-mobile-only/mobile-summary.json`
- Full-pass Mobile trace: `/Users/david/Public/Código/the-agency/output/playwright/deep-pass-2026-02-25-v6-mobile-only/mobile-trace.zip`
- Seed E2E: `/Users/david/Public/Código/the-agency/output/audit-seed-20260225074727.json`
- Recheck API backend-correcto: `/Users/david/Public/Código/the-agency/output/live-api-recheck-2026-02-25.txt`
- Recheck visual desktop/móvil:
  - `/Users/david/Public/Código/the-agency/output/playwright/live-recheck-2026-02-25/mobile-dashboard-current.png`
  - `/Users/david/Public/Código/the-agency/output/playwright/live-recheck-2026-02-25/mobile-finance-holded-current.png`
  - `/Users/david/Public/Código/the-agency/output/playwright/live-recheck-2026-02-25/desktop-dashboard-current.png`
  - `/Users/david/Public/Código/the-agency/output/playwright/live-recheck-2026-02-25/desktop-finance-holded-current.png`
  - `/Users/david/Public/Código/the-agency/output/playwright/live-recheck-2026-02-25/recheck-events-current.json`

## 3) Matriz de cobertura funcional (ruta por ruta)

Columnas:

- `Desktop ok`: token esperado encontrado en la pantalla.
- `D clicks/fail`: clics ejecutados / clics fallidos.
- `Mobile ok`: token esperado encontrado en la pantalla.
- `M clicks/fail`: clics ejecutados / clics fallidos.

| Ruta | Desktop ok | D clicks | D fail | Mobile ok | M clicks | M fail |
|---|---:|---:|---:|---:|---:|---:|
| `/dashboard` | true | 16 | 0 | false | 0 | 0 |
| `/clients` | true | 14 | 2 | false | 1 | 6 |
| `/leads` | true | 16 | 0 | false | 6 | 2 |
| `/projects` | true | 16 | 0 | false | 6 | 2 |
| `/tasks` | true | 16 | 0 | false | 3 | 7 |
| `/growth` | true | 12 | 4 | false | 5 | 0 |
| `/timesheet` | true | 14 | 0 | false | 1 | 1 |
| `/digests` | true | 14 | 2 | false | 6 | 0 |
| `/reports` | true | 16 | 0 | false | 5 | 0 |
| `/proposals` | true | 16 | 0 | true | 2 | 6 |
| `/billing` | true | 15 | 0 | true | 1 | 0 |
| `/finance` | true | 14 | 0 | true | 1 | 0 |
| `/finance/income` | true | 15 | 0 | true | 6 | 0 |
| `/finance/expenses` | true | 16 | 0 | true | 6 | 0 |
| `/finance/taxes` | true | 16 | 0 | true | 2 | 0 |
| `/finance/forecasts` | true | 16 | 0 | true | 6 | 0 |
| `/finance/advisor` | true | 15 | 0 | true | 2 | 0 |
| `/finance/import` | true | 14 | 0 | true | 1 | 0 |
| `/users` | true | 16 | 0 | false | 6 | 0 |
| `/discord` | true | 16 | 0 | false | 4 | 0 |
| `/finance-holded` | true | 16 | 0 | false | 8 | 0 |
| `/clients/2` | true | 16 | 0 | true | 6 | 0 |
| `/leads/2` | true | 16 | 0 | true | 6 | 2 |
| `/projects/2` | true | 16 | 0 | true | 6 | 2 |

Lectura de la matriz:

- La cobertura de rutas y clics fue completa.
- En móvil, varios `expected_ok=false` están correlacionados con crash de render (`InsightCard`) y estados transitorios.
- En revalidación backend-correcto, el crash de dashboard quedó confirmado también en desktop.

## 4) Hallazgos priorizados (bugs, seguridad, estabilidad)

## 4.1 Critical

### C-01) JWT forjable + token sin expiración aceptado

Estado: **Confirmado en revalidación backend-correcto**.

Impacto:

- Compromiso de autenticación.
- Suplantación de cualquier usuario (`sub` arbitrario), incluido admin.
- Persistencia indefinida de token sin `exp`.

Evidencia viva:

- Archivo: `/Users/david/Public/Código/the-agency/output/live-api-recheck-2026-02-25.txt`
- Resultado:
  - `GET /api/auth/me` con token forjado con clave por defecto -> `200`.
  - `GET /api/auth/me` con token forjado sin `exp` -> `200`.

Evidencia en código:

- `backend/config.py:8` define `DEFAULT_SECRET_KEY` insegura.
- `backend/config.py:13` usa esa clave por defecto si no se sobreescribe.
- `backend/core/security.py:27-30` decodifica JWT sin exigir claims obligatorios (`exp`, `iat`, etc.).

Recomendación inmediata:

1. Rotar `SECRET_KEY` y revocar sesiones activas.
2. Exigir `exp` en decode (y preferiblemente `iat`, `nbf`, `iss`, `aud`).
3. Bloquear arranque en producción si `SECRET_KEY == DEFAULT_SECRET_KEY`.

## 4.2 High

### H-01) Timesheet devuelve 500 por mezcla timezone naive/aware

Estado: **Confirmado en revalidación backend-correcto**.

Impacto:

- Timesheet inestable.
- Errores 500 frecuentes en consultas diarias/semanales.

Evidencia viva:

- `GET /api/time-entries?...date_from=...Z&date_to=...Z` -> `500`.
- Mismo endpoint sin `Z` -> `200`.
- `GET /api/time-entries/weekly?week_start=...` -> `500`.
- Evidencia: `/Users/david/Public/Código/the-agency/output/live-api-recheck-2026-02-25.txt`.

Evidencia de stacktrace:

- `TypeError: can't subtract offset-naive and offset-aware datetimes`.
- Query contra `TIMESTAMP WITHOUT TIME ZONE` con datetime aware.

Evidencia en código:

- `backend/api/routes/time_entries.py:66-67` recibe `date_from/date_to` como `datetime`.
- `backend/api/routes/time_entries.py:79-82` compara directamente contra `TimeEntry.date`.
- `backend/api/routes/time_entries.py:97-98` crea `start_dt/end_dt` con `tzinfo=UTC`.
- `backend/api/routes/time_entries.py:120-121` usa esos aware datetimes en filtro SQL.
- `frontend/src/pages/timesheet-page.tsx:47` envía `Z` explícita.

Recomendación:

1. Unificar estrategia temporal de extremo a extremo (UTC-aware en DB/API o normalización explícita).
2. Añadir tests de contrato con fechas naive y aware.

### H-02) Holded dashboard/facturas/gastos 500 por schema tipado incorrectamente

Estado: **Confirmado en revalidación backend-correcto**.

Impacto:

- Módulo Holded no operativo.
- Carga infinita y toast de error en UI.

Evidencia viva:

- `/api/holded/config` -> `200`.
- `/api/holded/dashboard` -> `500`.
- `/api/holded/invoices` -> `500`.
- `/api/holded/expenses` -> `500`.
- Evidencia: `/Users/david/Public/Código/the-agency/output/live-api-recheck-2026-02-25.txt`.

Evidencia de stacktrace:

- `ValidationError` de Pydantic: campos `pending_invoices.*.date/due_date` esperan `None`.
- Punto de fallo en `backend/api/routes/holded.py:465` al construir `HoldedDashboardResponse`.

Evidencia en código:

- `backend/schemas/holded.py:42-43` y `:60` usan `date: Optional[date]` con colisión del nombre del campo `date`.

Recomendación:

1. Alias de tipo de fecha (`from datetime import date as dt_date`) y uso consistente `Optional[dt_date]`.
2. Tests de serialización response para `HoldedInvoiceResponse` y `HoldedDashboardResponse`.

### H-03) Crash de dashboard por `InsightType=quality` no soportado en frontend (desktop y móvil)

Estado: **Confirmado en revalidación backend-correcto**.

Impacto:

- Pantalla negra en dashboard (desktop y móvil).
- Error de render global por icono undefined.

Evidencia viva:

- Screenshot móvil negro: `/Users/david/Public/Código/the-agency/output/playwright/live-recheck-2026-02-25/mobile-dashboard-current.png`
- Screenshot desktop negro: `/Users/david/Public/Código/the-agency/output/playwright/live-recheck-2026-02-25/desktop-dashboard-current.png`
- Eventos: `/Users/david/Public/Código/the-agency/output/playwright/live-recheck-2026-02-25/recheck-events-current.json`
  - `pageerror`: `Check the render method of InsightCard`.

Evidencia en código:

- Backend emite `InsightType.quality`:
  - `backend/services/insights.py:240`
  - `backend/services/insights.py:254`
  - `backend/services/insights.py:268`
- Frontend no contempla `quality` en unión:
  - `frontend/src/lib/types.ts:363`
- Mapa de iconos sin fallback:
  - `frontend/src/components/pm/insights-panel.tsx:24-31`
  - Uso directo `const Icon = TYPE_ICONS[...]` en `:172` y render `<Icon .../>` en `:189`.

Recomendación:

1. Añadir `quality` a `InsightType` frontend.
2. Añadir fallback defensivo de icono/tipo desconocido.
3. Añadir test de render con todos los tipos backend.

### H-04) `POST /api/digests/generate` devuelve 500 ante fallos no-ValueError

Estado: **Confirmado en revalidación backend-correcto**.

Impacto:

- Función core de digests no resiliente.

Evidencia viva:

- `POST /api/digests/generate` -> `500`.
- Evidencia: `/Users/david/Public/Código/the-agency/output/live-api-recheck-2026-02-25.txt`.

Evidencia en código:

- `backend/api/routes/digests.py:109-112` captura solo `ValueError`.

Recomendación:

1. Capturar `httpx`/timeout/excepciones proveedor y mapear a `502/503`.
2. Añadir mensaje de error controlado + fallback local cuando sea posible.

### H-05) Endpoints Discord 500 por excepciones de red no controladas

Estado: **Confirmado en revalidación backend-correcto**.

Impacto:

- Integración frágil.
- UX de error genérico en test/envío.

Evidencia viva:

- `POST /api/discord/test-webhook` -> `500`.
- `POST /api/discord/send-daily-summary` -> `500`.
- Evidencia: `/Users/david/Public/Código/the-agency/output/live-api-recheck-2026-02-25.txt`.

Evidencia en código:

- `backend/api/routes/discord.py:56-65` llama a `httpx.AsyncClient.post` sin `try/except`.

Recomendación:

1. Manejar explícitamente `httpx.HTTPError`.
2. Responder con `200 success=false` o `502` semántico, no 500 genérico.

## 4.3 Medium

### M-01) Exposición de datos de usuarios a cualquier autenticado

Estado: **Confirmado en revalidación backend-correcto**.

Impacto:

- Un member puede listar usuarios y leer datos de admin (email, tarifa).

Evidencia viva:

- Member:
  - `GET /api/users?page_size=999` -> `200`
  - `GET /api/users/1` -> `200`
- Evidencia: `/Users/david/Public/Código/the-agency/output/live-api-recheck-2026-02-25.txt`.

Evidencia en código:

- `backend/api/routes/users.py:16-22` usa `get_current_user` (sin admin/module guard).
- `backend/api/routes/users.py:57-62` mismo patrón.

Recomendación:

1. Limitar a admin/modulo users.
2. Endpoint separado para perfil propio.

### M-02) Credenciales bootstrap en `seed.py`

Impacto:

- Riesgo operativo si seed se usa fuera de entorno controlado.

Evidencia en código:

- `backend/db/seed.py:12-26` incluye contraseñas de usuarios bootstrap.

Recomendación:

1. Generación por entorno/primer arranque.
2. No mantener credenciales estáticas en el repositorio.

### M-03) Cambios DDL en startup de app

Impacto:

- Arranque frágil y difícil de operar en despliegues concurrentes.

Evidencia en código:

- `backend/main.py` ejecuta creación/alteraciones de esquema en `lifespan`.

Recomendación:

- Migraciones Alembic versionadas para todos los cambios de schema.

### M-04) Entorno Python del backend no reproducible (venv roto)

Impacto:

- Scripts de verificación y operación fallan en el entorno actual.

Evidencia:

- `backend/venv/bin/python` falla con `Library not loaded: @executable_path/../Python3`.

Recomendación:

- Recrear `venv` local y evitar versionar/trasladar venv entre rutas distintas.

## 4.4 Low

### L-01) Estado “Holded conectado” no refleja salud real del módulo

Evidencia:

- UI muestra conectado mientras dashboard/invoices/expenses devuelven 500.

Recomendación:

- Estado compuesto: config + salud endpoints + timestamp último sync válido.

### L-02) Métrica `expected_ok` de la pasada full no debe usarse sola como criterio de éxito

Contexto:

- `expected_ok` depende de token textual y puede degradarse por crash de render o timing.

Recomendación:

- Añadir assertions estructurales (`data-testid`, `error-boundary`) y oracle de API por pantalla.

## 5) Segunda pasada de seguridad (matriz)

## 5.1 Controles ejecutados (backend-correcto)

| Control | Prueba | Resultado |
|---|---|---|
| AuthN | Token forjado con clave default -> `/api/auth/me` | **FAIL** (`200`) |
| AuthN | Token forjado sin `exp` -> `/api/auth/me` | **FAIL** (`200`) |
| AuthZ | Member `GET /api/users` | **FAIL** (`200`) |
| AuthZ | Member `GET /api/users/1` | **FAIL** (`200`) |
| AuthZ | Member `PUT /api/users/1/permissions` | PASS (`403`) |
| AuthZ | Member `GET /api/finance/income` | PASS (`403`) |
| AuthZ | Member `GET /api/holded/config` | PASS (`403`) |
| Data Integrity | `time-entries` con fechas `Z` | **FAIL** (`500`) |
| Data Integrity | `time-entries` sin `Z` | PASS (`200`) |
| Integración | Holded dashboard/invoices/expenses | **FAIL** (`500`) |
| Integración | Discord test/send | **FAIL** (`500`) |
| Integración | Digests generate | **FAIL** (`500`) |
| UI Runtime | Dashboard desktop/móvil render | **FAIL** (pantalla negra + `InsightCard` error) |

## 5.2 Matriz de riesgo (seguridad + disponibilidad)

| ID | Riesgo | Probabilidad | Impacto | Nivel | Estado |
|---|---|---|---|---|---|
| SEC-01 | JWT forjable por secret por defecto | Alta | Crítico | **Crítico** | Abierto |
| SEC-02 | JWT sin `exp` válido | Alta | Alto | **Crítico** | Abierto |
| SEC-03 | Exposición de usuarios a member | Alta | Medio-Alto | **Alto** | Abierto |
| SEC-04 | Holded 500 sistemático | Alta | Alto | **Alto** | Abierto |
| SEC-05 | Discord/Digests con 500 no controlado | Alta | Medio-Alto | **Alto** | Abierto |
| SEC-06 | Timesheet 500 por timezone | Alta | Medio-Alto | **Alto** | Abierto |
| SEC-07 | Credenciales bootstrap en seed | Media | Medio | **Medio** | Abierto |

## 6) Optimizaciones y mejoras técnicas

## 6.1 Backend

1. Contrato temporal único (ideal: UTC-aware end-to-end).
2. Hardening JWT (`exp` obligatorio, `iss/aud`, rotación de claves).
3. Patrón unificado de errores de integraciones (`400/409/422/502/503` con cuerpo consistente).
4. Migraciones Alembic completas en lugar de DDL runtime.
5. Circuit-breaker/retry/backoff para proveedores externos (Holded/Discord/LLM).

## 6.2 Frontend

1. Contrato de tipos auto-generado desde OpenAPI (evita drift como `quality`).
2. Error boundary por zona crítica (Dashboard/Finanzas) para evitar pantalla negra total.
3. Fallback seguro en componentes dinámicos (`InsightCard` icon/type unknown).
4. Estados de salud de integración visibles y accionables (no solo “conectado”).

## 6.3 Observabilidad

1. Trazabilidad por `request_id` en backend y correlación con frontend.
2. Dashboard de errores por endpoint y por pantalla.
3. Alertas automáticas en rutas críticas:
   - `/api/auth/*`
   - `/api/time-entries*`
   - `/api/holded/*`
   - `/api/discord/*`
   - `/api/digests/generate`

## 7) Ideas de producto (alto impacto)

1. Centro de salud operativa por módulo (CRM, PM, Finanzas, Integraciones).
2. Modo degradado inteligente para integraciones caídas (cache última sync válida).
3. Indicador de calidad de datos: tareas sin responsable/estimación/fecha.
4. Simulador de permisos por rol para prevenir fugas antes de desplegar.
5. Replay de sesión ante crashes críticos de UI.
6. Alertas semanales automáticas de riesgo operativo (seguridad + disponibilidad + datos).
7. Checklist de cierre mensual con validaciones financieras y operativas automáticas.

## 8) Plan de remediación

## Fase 0 (0-48h)

1. Rotar `SECRET_KEY` y revocar sesiones.
2. Exigir `exp` en decode JWT.
3. Hotfix frontend `InsightType` + fallback icono.
4. Hotfix Holded schema de fechas.
5. Hotfix timesheet naive/aware.

Criterio de salida Fase 0:

- `/api/auth/me` rechaza token forjado y token sin `exp`.
- Dashboard renderiza en desktop y móvil sin pageerror.
- `/api/holded/dashboard|invoices|expenses` dejan de devolver 500.
- `/api/time-entries` con `Z` y `/weekly` devuelven 200.

## Fase 1 (3-7 días)

1. Endurecer autorización de `/api/users`.
2. Manejo robusto de errores Discord/Digests.
3. Tests de regresión API/UI para hallazgos críticos.
4. Telemetría de errores de render y endpoints críticos.

## Fase 2 (2-3 semanas)

1. OpenAPI -> tipos frontend auto-generados.
2. Migración completa de DDL runtime a Alembic.
3. Rate limiting y antifuerza bruta en auth.
4. Hardening secretos y bootstrapping seguro.

## Fase 3 (continuo)

1. Re-auditoría mensual de seguridad y disponibilidad.
2. SLO por módulo (error budget + alertas).
3. Chaos testing de integraciones externas.

## 9) Checklist de cierre de auditoría

- Revisión de código backend/frontend: Sí.
- Cobertura viva full-pass desktop: Sí.
- Cobertura viva full-pass móvil: Sí.
- Revalidación backend-correcto: Sí.
- Segunda pasada de seguridad con matriz: Sí.
- Plan de remediación por fases: Sí.
- Ideas y optimizaciones: Sí.

## 10) Conclusión

La plataforma cubre funcionalidad amplia, pero en su estado actual no es apta para un entorno de producción robusto por la combinación de:

- vulnerabilidad crítica de autenticación JWT,
- crash de dashboard (desktop/móvil),
- errores 500 en timesheet y Holded,
- fragilidad en integraciones clave (Discord/Digests).

Prioridad inmediata: ejecutar Fase 0 completa y repetir una pasada viva completa (desktop/móvil) con backend-correcto para certificar estabilidad antes de nuevos despliegues.

## Anexo A) Métricas de ejecución full-pass

Desktop (`deep-pass-2026-02-25-v5`):

- `routes_total=24`
- `routes_expected_ok=24`
- `events_total=652`
- `api_http_error=326`
- `api_500=64`

Mobile (`deep-pass-2026-02-25-v6-mobile-only`):

- `routes_total=24`
- `routes_expected_ok=12`
- `events_total=216`
- `api_http_error=100`
- `api_500=14`
- `pageerror=16`

Nota: el ruido 422 masivo de la pasada full no se reprodujo en la revalidación backend-correcto para endpoints con `page_size=999`; por tanto se considera **no accionable** como bug backend de `the-agency` en esta versión.

## Anexo B) Detalle click-by-click por ruta (desktop + móvil)

### /dashboard
- Desktop: clicked=16 fail=0 expected_ok=true
- Desktop clicked: Dashboard | /dashboard; Clientes | /clients; Pipeline | /leads; Proyectos | /projects; Tareas | /tasks; Growth | /growth; Timesheet | /timesheet; Digests | /digests; Informes | /reports; Presupuestos | /proposals; Facturacion | /billing; Finanzas (Holded) | /finance-holded; Equipo | /users; Discord | /discord; Enviar resumen de hoy
- Desktop failed: -
- Mobile: clicked=0 fail=0 expected_ok=false
- Mobile clicked: -
- Mobile failed: -

### /clients
- Desktop: clicked=14 fail=2 expected_ok=true
- Desktop clicked: Dashboard | /dashboard; Pipeline | /leads; Proyectos | /projects; Tareas | /tasks; Growth | /growth; Timesheet | /timesheet; Digests | /digests; Informes | /reports; Presupuestos | /proposals; Facturacion | /billing; Finanzas (Holded) | /finance-holded; Equipo | /users; Discord | /discord; Enviar resumen de hoy
- Desktop failed: Clientes | /clients; Probar
- Mobile: clicked=1 fail=6 expected_ok=false
- Mobile clicked: Nuevo cliente
- Mobile failed: Todos; Activos; Pausados; Finalizados; AUDIT-20260225074727-lqsr Cliente | /clients/2; AUDIT-20260225073908-bcmc Cliente | /clients/1

### /leads
- Desktop: clicked=16 fail=0 expected_ok=true
- Desktop clicked: Dashboard | /dashboard; Clientes | /clients; Pipeline | /leads; Proyectos | /projects; Tareas | /tasks; Growth | /growth; Timesheet | /timesheet; Digests | /digests; Informes | /reports; Presupuestos | /proposals; Facturacion | /billing; Finanzas (Holded) | /finance-holded; Equipo | /users; Discord | /discord; Enviar resumen de hoy
- Desktop failed: -
- Mobile: clicked=6 fail=2 expected_ok=false
- Mobile clicked: Nuevo lead; Cerrar; Clientes | /clients; Pipeline | /leads; Finanzas | /finance-holded; Proyectos | /projects
- Mobile failed: Ganados (0); Perdidos (0)

### /projects
- Desktop: clicked=16 fail=0 expected_ok=true
- Desktop clicked: Dashboard | /dashboard; Clientes | /clients; Pipeline | /leads; Proyectos | /projects; Tareas | /tasks; Growth | /growth; Timesheet | /timesheet; Digests | /digests; Informes | /reports; Presupuestos | /proposals; Facturacion | /billing; Finanzas (Holded) | /finance-holded; Equipo | /users; Discord | /discord; Enviar resumen de hoy
- Desktop failed: -
- Mobile: clicked=6 fail=2 expected_ok=false
- Mobile clicked: Nuevo vacío; Cerrar; Clientes | /clients; AUDIT-20260225074727-lqsr Cliente | /clients/2; facturas; Home | /dashboard
- Mobile failed: Desde plantilla; Crear primer proyecto

### /tasks
- Desktop: clicked=16 fail=0 expected_ok=true
- Desktop clicked: Dashboard | /dashboard; Clientes | /clients; Pipeline | /leads; Proyectos | /projects; Tareas | /tasks; Growth | /growth; Timesheet | /timesheet; Digests | /digests; Informes | /reports; Presupuestos | /proposals; Facturacion | /billing; Finanzas (Holded) | /finance-holded; Equipo | /users; Discord | /discord; Enviar resumen de hoy
- Desktop failed: -
- Mobile: clicked=3 fail=7 expected_ok=false
- Mobile clicked: Nueva tarea; Cerrar; Clientes | /clients
- Mobile failed: ⚠️ Sin Asignar; ⚠️ Sin Fechas; ⚠️ Sin Estimación; 🔥 Atrasadas; Mi Día; Tablero; Todas

### /growth
- Desktop: clicked=12 fail=4 expected_ok=true
- Desktop clicked: Dashboard | /dashboard; Pipeline | /leads; Tareas | /tasks; Growth | /growth; Timesheet | /timesheet; Digests | /digests; Facturacion | /billing; Finanzas (Holded) | /finance-holded; Equipo | /users; Discord | /discord; Enviar resumen de hoy; Probar
- Desktop failed: Clientes | /clients; Proyectos | /projects; Informes | /reports; Presupuestos | /proposals
- Mobile: clicked=5 fail=0 expected_ok=false
- Mobile clicked: Nueva Idea; Cerrar; Clientes | /clients; Finalizados; Home | /dashboard
- Mobile failed: -

### /timesheet
- Desktop: clicked=14 fail=0 expected_ok=true
- Desktop clicked: Dashboard | /dashboard; Clientes | /clients; Pipeline | /leads; Proyectos | /projects; Tareas | /tasks; Growth | /growth; Timesheet | /timesheet; Digests | /digests; Informes | /reports; Presupuestos | /proposals; Facturacion | /billing; Finanzas (Holded) | /finance-holded; Equipo | /users; Discord | /discord
- Desktop failed: -
- Mobile: clicked=1 fail=1 expected_ok=false
- Mobile clicked: Home | /dashboard
- Mobile failed: Configurar alertas

### /digests
- Desktop: clicked=14 fail=2 expected_ok=true
- Desktop clicked: Dashboard | /dashboard; Clientes | /clients; Pipeline | /leads; Proyectos | /projects; Tareas | /tasks; Growth | /growth; Timesheet | /timesheet; Informes | /reports; Presupuestos | /proposals; Facturacion | /billing; Equipo | /users; Discord | /discord; Enviar resumen de hoy; Probar
- Desktop failed: Digests | /digests; Finanzas (Holded) | /finance-holded
- Mobile: clicked=6 fail=0 expected_ok=false
- Mobile clicked: Generar todos; Generar digest; Cerrar; Clientes | /clients; Finalizados; Home | /dashboard
- Mobile failed: -

### /reports
- Desktop: clicked=16 fail=0 expected_ok=true
- Desktop clicked: Dashboard | /dashboard; Clientes | /clients; Pipeline | /leads; Proyectos | /projects; Tareas | /tasks; Growth | /growth; Timesheet | /timesheet; Digests | /digests; Informes | /reports; Presupuestos | /proposals; Facturacion | /billing; Finanzas (Holded) | /finance-holded; Equipo | /users; Discord | /discord; Enviar resumen de hoy
- Desktop failed: -
- Mobile: clicked=5 fail=0 expected_ok=false
- Mobile clicked: Generar informe; Cerrar; Clientes | /clients; Finalizados; Home | /dashboard
- Mobile failed: -

### /proposals
- Desktop: clicked=16 fail=0 expected_ok=true
- Desktop clicked: Dashboard | /dashboard; Clientes | /clients; Pipeline | /leads; Proyectos | /projects; Tareas | /tasks; Growth | /growth; Timesheet | /timesheet; Digests | /digests; Informes | /reports; Presupuestos | /proposals; Facturacion | /billing; Finanzas (Holded) | /finance-holded; Equipo | /users; Discord | /discord; Enviar resumen de hoy
- Desktop failed: -
- Mobile: clicked=2 fail=6 expected_ok=true
- Mobile clicked: Nueva Propuesta; 1Datos basicos
- Mobile failed: Todas; Borradores; Enviadas; Aceptadas; Rechazadas; PDF

### /billing
- Desktop: clicked=15 fail=0 expected_ok=true
- Desktop clicked: Dashboard | /dashboard; Clientes | /clients; Pipeline | /leads; Proyectos | /projects; Tareas | /tasks; Growth | /growth; Timesheet | /timesheet; Digests | /digests; Informes | /reports; Presupuestos | /proposals; Facturacion | /billing; Finanzas (Holded) | /finance-holded; Equipo | /users; Discord | /discord; Enviar resumen de hoy
- Desktop failed: -
- Mobile: clicked=1 fail=0 expected_ok=true
- Mobile clicked: Descargar CSV
- Mobile failed: -

### /finance
- Desktop: clicked=14 fail=0 expected_ok=true
- Desktop clicked: Dashboard | /dashboard; Clientes | /clients; Pipeline | /leads; Proyectos | /projects; Tareas | /tasks; Growth | /growth; Timesheet | /timesheet; Digests | /digests; Informes | /reports; Presupuestos | /proposals; Facturacion | /billing; Finanzas (Holded) | /finance-holded; Equipo | /users; Discord | /discord
- Desktop failed: -
- Mobile: clicked=1 fail=0 expected_ok=true
- Mobile clicked: Home | /dashboard
- Mobile failed: -

### /finance/income
- Desktop: clicked=15 fail=0 expected_ok=true
- Desktop clicked: Dashboard | /dashboard; Clientes | /clients; Pipeline | /leads; Proyectos | /projects; Tareas | /tasks; Growth | /growth; Timesheet | /timesheet; Digests | /digests; Informes | /reports; Presupuestos | /proposals; Facturacion | /billing; Finanzas (Holded) | /finance-holded; Equipo | /users; Discord | /discord; Enviar resumen de hoy
- Desktop failed: -
- Mobile: clicked=6 fail=0 expected_ok=true
- Mobile clicked: Nuevo ingreso; Cerrar; Clientes | /clients; AUDIT-20260225074727-lqsr Cliente | /clients/2; facturas; Home | /dashboard
- Mobile failed: -

### /finance/expenses
- Desktop: clicked=16 fail=0 expected_ok=true
- Desktop clicked: Dashboard | /dashboard; Clientes | /clients; Pipeline | /leads; Proyectos | /projects; Tareas | /tasks; Growth | /growth; Timesheet | /timesheet; Digests | /digests; Informes | /reports; Presupuestos | /proposals; Facturacion | /billing; Finanzas (Holded) | /finance-holded; Equipo | /users; Discord | /discord; Enviar resumen de hoy
- Desktop failed: -
- Mobile: clicked=6 fail=0 expected_ok=true
- Mobile clicked: Nuevo gasto; Cerrar; Clientes | /clients; AUDIT-20260225074727-lqsr Cliente | /clients/2; facturas; Home | /dashboard
- Mobile failed: -

### /finance/taxes
- Desktop: clicked=16 fail=0 expected_ok=true
- Desktop clicked: Dashboard | /dashboard; Clientes | /clients; Pipeline | /leads; Proyectos | /projects; Tareas | /tasks; Growth | /growth; Timesheet | /timesheet; Digests | /digests; Informes | /reports; Presupuestos | /proposals; Facturacion | /billing; Finanzas (Holded) | /finance-holded; Equipo | /users; Discord | /discord; Enviar resumen de hoy
- Desktop failed: -
- Mobile: clicked=2 fail=0 expected_ok=true
- Mobile clicked: Calcular; Manual
- Mobile failed: -

### /finance/forecasts
- Desktop: clicked=16 fail=0 expected_ok=true
- Desktop clicked: Dashboard | /dashboard; Clientes | /clients; Pipeline | /leads; Proyectos | /projects; Tareas | /tasks; Growth | /growth; Timesheet | /timesheet; Digests | /digests; Informes | /reports; Presupuestos | /proposals; Facturacion | /billing; Finanzas (Holded) | /finance-holded; Equipo | /users; Discord | /discord; Enviar resumen de hoy
- Desktop failed: -
- Mobile: clicked=6 fail=0 expected_ok=true
- Mobile clicked: Generar; Manual; Cerrar; Clientes | /clients; Finalizados; Home | /dashboard
- Mobile failed: -

### /finance/advisor
- Desktop: clicked=15 fail=0 expected_ok=true
- Desktop clicked: Dashboard | /dashboard; Clientes | /clients; Pipeline | /leads; Proyectos | /projects; Tareas | /tasks; Growth | /growth; Timesheet | /timesheet; Digests | /digests; Informes | /reports; Presupuestos | /proposals; Facturacion | /billing; Finanzas (Holded) | /finance-holded; Equipo | /users; Discord | /discord; Enviar resumen de hoy
- Desktop failed: -
- Mobile: clicked=2 fail=0 expected_ok=true
- Mobile clicked: Hecho; Home | /dashboard
- Mobile failed: -

### /finance/import
- Desktop: clicked=14 fail=0 expected_ok=true
- Desktop clicked: Dashboard | /dashboard; Clientes | /clients; Pipeline | /leads; Proyectos | /projects; Tareas | /tasks; Growth | /growth; Timesheet | /timesheet; Digests | /digests; Informes | /reports; Presupuestos | /proposals; Facturacion | /billing; Finanzas (Holded) | /finance-holded; Equipo | /users; Discord | /discord
- Desktop failed: -
- Mobile: clicked=1 fail=0 expected_ok=true
- Mobile clicked: Home | /dashboard
- Mobile failed: -

### /users
- Desktop: clicked=16 fail=0 expected_ok=true
- Desktop clicked: Dashboard | /dashboard; Clientes | /clients; Pipeline | /leads; Proyectos | /projects; Tareas | /tasks; Growth | /growth; Timesheet | /timesheet; Digests | /digests; Informes | /reports; Presupuestos | /proposals; Facturacion | /billing; Finanzas (Holded) | /finance-holded; Equipo | /users; Discord | /discord; Enviar resumen de hoy
- Desktop failed: -
- Mobile: clicked=6 fail=0 expected_ok=false
- Mobile clicked: Invitar Miembro; Cerrar; Clientes | /clients; AUDIT-20260225074727-lqsr Cliente | /clients/2; facturas; Home | /dashboard
- Mobile failed: -

### /discord
- Desktop: clicked=16 fail=0 expected_ok=true
- Desktop clicked: Dashboard | /dashboard; Clientes | /clients; Pipeline | /leads; Proyectos | /projects; Tareas | /tasks; Growth | /growth; Timesheet | /timesheet; Digests | /digests; Informes | /reports; Presupuestos | /proposals; Facturacion | /billing; Finanzas (Holded) | /finance-holded; Equipo | /users; Discord | /discord; Enviar resumen de hoy
- Desktop failed: -
- Mobile: clicked=4 fail=0 expected_ok=false
- Mobile clicked: Enviar resumen de hoy; Probar; Guardar configuracion; Home | /dashboard
- Mobile failed: -

### /finance-holded
- Desktop: clicked=16 fail=0 expected_ok=true
- Desktop clicked: Dashboard | /dashboard; Clientes | /clients; Pipeline | /leads; Proyectos | /projects; Tareas | /tasks; Growth | /growth; Timesheet | /timesheet; Digests | /digests; Informes | /reports; Presupuestos | /proposals; Facturacion | /billing; Finanzas (Holded) | /finance-holded; Equipo | /users; Discord | /discord; Enviar resumen de hoy
- Desktop failed: -
- Mobile: clicked=8 fail=0 expected_ok=false
- Mobile clicked: Sincronizar; Resumen; Facturas; Gastos; Configuracion; Probar conexion; Sync contactos; Home | /dashboard
- Mobile failed: -

### /clients/2
- Desktop: clicked=16 fail=0 expected_ok=true
- Desktop clicked: Dashboard | /dashboard; Clientes | /clients; Pipeline | /leads; Proyectos | /projects; Tareas | /tasks; Growth | /growth; Timesheet | /timesheet; Digests | /digests; Informes | /reports; Presupuestos | /proposals; Facturacion | /billing; Finanzas (Holded) | /finance-holded; Equipo | /users; Discord | /discord; Enviar resumen de hoy
- Desktop failed: -
- Mobile: clicked=6 fail=0 expected_ok=true
- Mobile clicked: /clients; Todos; Activos; Pausados; Finalizados; Home | /dashboard
- Mobile failed: -

### /leads/2
- Desktop: clicked=16 fail=0 expected_ok=true
- Desktop clicked: Dashboard | /dashboard; Clientes | /clients; Pipeline | /leads; Proyectos | /projects; Tareas | /tasks; Growth | /growth; Timesheet | /timesheet; Digests | /digests; Informes | /reports; Presupuestos | /proposals; Facturacion | /billing; Finanzas (Holded) | /finance-holded; Equipo | /users; Discord | /discord; Enviar resumen de hoy
- Desktop failed: -
- Mobile: clicked=6 fail=2 expected_ok=true
- Mobile clicked: /leads; Nuevo lead; Cerrar; Clientes | /clients; AUDIT-20260225073908-bcmc Cliente | /clients/1; Home | /dashboard
- Mobile failed: Ganados (0); Perdidos (0)

### /projects/2
- Desktop: clicked=16 fail=0 expected_ok=true
- Desktop clicked: Dashboard | /dashboard; Clientes | /clients; Pipeline | /leads; Proyectos | /projects; Tareas | /tasks; Growth | /growth; Timesheet | /timesheet; Digests | /digests; Informes | /reports; Presupuestos | /proposals; Facturacion | /billing; Finanzas (Holded) | /finance-holded; Equipo | /users; Discord | /discord; Enviar resumen de hoy
- Desktop failed: -
- Mobile: clicked=6 fail=2 expected_ok=true
- Mobile clicked: /projects; Desde plantilla; Cerrar; Clientes | /clients; AUDIT-20260225073908-bcmc Cliente | /clients/1; Home | /dashboard
- Mobile failed: AUDIT-20260225074727-lqsr ProyectoAUDIT-20260225074727-lqsr ClientePlanificación0%27 mar0/1 tareas | /projects/2; AUDIT-20260225073908-bcmc ProyectoAUDIT-20260225073908-bcmc ClienteActivo0%27 mar0/1 tareas | /projects/1

