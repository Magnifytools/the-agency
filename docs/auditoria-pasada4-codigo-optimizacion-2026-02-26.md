# Auditoría Completa de Código y Optimización — The Agency (Pasada 4)

Fecha: 2026-02-26
Alcance: backend + frontend (análisis estático + checks automáticos)
Modo: solo auditoría, recomendaciones y fixes propuestos (sin cambios de código)

## 1) Resumen ejecutivo

Estado general: funcional, pero con riesgos importantes de seguridad/autorización y deuda técnica que afecta fiabilidad operativa.

Hallazgos por severidad:

- Crítico: 3
- Alto: 4
- Medio: 6

Bloqueadores principales:

1. Mutaciones protegidas con permisos de lectura (RBAC write-bypass).
2. Endpoint de PDF de propuestas con token en query string y control de autorización incompleto.
3. Exposición de dailys (list/get) sin restricción por propietario para usuarios no-admin.

## 2) Evidencia automática ejecutada

Frontend:

- `npm run lint` -> falla con 26 errores y 3 warnings.
- `npm run test` -> OK (29/29).
- `npm run build` -> OK.

Backend:

- No hay suite de tests backend detectada.
- `python3 -m compileall` (con `PYTHONPYCACHEPREFIX=/tmp/...`) -> OK.
- Import runtime parcial en entorno actual: `backend.main` falla por dependencia faltante (`asyncpg`) fuera de venv; venv del proyecto está roto (`backend/venv/bin/python` no arranca).

## 3) Hallazgos críticos

### C-01) RBAC: endpoints de escritura aceptan permisos de lectura

Impacto:

- Un usuario con `can_read=true` y `can_write=false` podría crear/editar/borrar en módulos críticos.
- El modelo RBAC existe, pero se está aplicando de forma inconsistente en mutaciones.

Evidencia:

- `require_module(module)` sin `write=True` en mutaciones.
- Conteo detectado: 30 endpoints de mutación con este patrón.

Referencias (ejemplos representativos):

- `/Users/david/Public/Código/the-agency/backend/api/routes/tasks.py:94`
- `/Users/david/Public/Código/the-agency/backend/api/routes/tasks.py:144`
- `/Users/david/Public/Código/the-agency/backend/api/routes/tasks.py:189`
- `/Users/david/Public/Código/the-agency/backend/api/routes/clients.py:42`
- `/Users/david/Public/Código/the-agency/backend/api/routes/clients.py:109`
- `/Users/david/Public/Código/the-agency/backend/api/routes/projects.py:126`
- `/Users/david/Public/Código/the-agency/backend/api/routes/projects.py:237`
- `/Users/david/Public/Código/the-agency/backend/api/routes/sync.py:30`
- `/Users/david/Public/Código/the-agency/backend/api/routes/dashboard.py:313`

Fix recomendado:

1. En toda mutación (`POST/PUT/PATCH/DELETE`) usar `Depends(require_module("...", write=True))` salvo casos explícitos justificados.
2. Añadir test de contrato RBAC matriz `role/module/read/write` por endpoint.
3. Añadir script CI que falle si detecta mutación con `require_module` sin `write=True`.

---

### C-02) Propuestas PDF: token en query + autorización incompleta

Impacto:

- Token JWT expuesto en URL (logs, history, referer, capturas).
- Endpoint `/pdf` valida token pero no aplica `get_current_user` ni `require_module("proposals")`.
- Un token válido puede leer propuestas por ID sin control de permisos por módulo.

Evidencia:

Backend:

- `/Users/david/Public/Código/the-agency/backend/api/routes/proposals.py:642`
- `/Users/david/Public/Código/the-agency/backend/api/routes/proposals.py:648`
- `/Users/david/Public/Código/the-agency/backend/api/routes/proposals.py:652`

Frontend:

- `/Users/david/Public/Código/the-agency/frontend/src/pages/proposals-page.tsx:342`
- `/Users/david/Public/Código/the-agency/frontend/src/pages/proposals-page.tsx:343`

Fix recomendado:

1. Eliminar token en query y usar `Authorization: Bearer` normal.
2. Proteger `GET /api/proposals/{id}/pdf` con `Depends(require_module("proposals"))` o `get_current_user` + policy explícita.
3. Si necesitas abrir en pestaña nueva, usar URL firmada corta one-time (expira en segundos) sin reutilizar access token principal.

---

### C-03) Privacidad: dailys visibles fuera del propietario

Impacto:

- Usuarios autenticados pueden listar y leer dailys de otros (si conocen IDs o sin filtro de usuario).
- Riesgo de exposición de información operativa interna.

Evidencia:

- `list_dailys` no restringe por owner cuando no es admin:
  - `/Users/david/Public/Código/the-agency/backend/api/routes/dailys.py:82`
  - `/Users/david/Public/Código/the-agency/backend/api/routes/dailys.py:94`
- `get_daily` tampoco valida owner/admin:
  - `/Users/david/Public/Código/the-agency/backend/api/routes/dailys.py:112`
  - `/Users/david/Public/Código/the-agency/backend/api/routes/dailys.py:119`

Fix recomendado:

1. En `list_dailys`, si `current_user.role != admin`, forzar `DailyUpdate.user_id == current_user.id`.
2. En `get_daily`, validar owner/admin igual que ya se hace en `reparse` y `delete`.
3. Añadir tests de autorización (member A no puede leer dailys de member B).

## 4) Hallazgos altos

### H-01) Endpoints de contactos/recursos/billing-events no pasan por `require_module`

Impacto:

- Bypass parcial del esquema de permisos por módulo.
- Cualquier autenticado puede operar rutas sensibles de cliente si conoce IDs.

Evidencia:

- Billing events usa solo `get_current_user`:
  - `/Users/david/Public/Código/the-agency/backend/api/routes/billing_events.py:54`
  - `/Users/david/Public/Código/the-agency/backend/api/routes/billing_events.py:71`
- Contacts idem:
  - `/Users/david/Public/Código/the-agency/backend/api/routes/contacts.py:27`
  - `/Users/david/Public/Código/the-agency/backend/api/routes/contacts.py:43`
- Resources idem:
  - `/Users/david/Public/Código/the-agency/backend/api/routes/resources.py:27`
  - `/Users/david/Public/Código/the-agency/backend/api/routes/resources.py:43`

Fix recomendado:

- Aplicar `require_module("clients")` + `write=True` en mutaciones.
- Si se requiere ownership por cliente/equipo, implementar scope adicional.

---

### H-02) Integridad financiera: usuario puede editar su propio `hourly_rate`

Impacto:

- Un member puede alterar su coste/hora y distorsionar métricas de coste/margen.

Evidencia:

- `UserUpdate` permite `hourly_rate`:
  - `/Users/david/Public/Código/the-agency/backend/schemas/user.py:16`
  - `/Users/david/Public/Código/the-agency/backend/schemas/user.py:18`
- `update_user` solo bloquea cambio de rol, no tarifa:
  - `/Users/david/Public/Código/the-agency/backend/api/routes/users.py:102`
  - `/Users/david/Public/Código/the-agency/backend/api/routes/users.py:110`

Fix recomendado:

- Permitir `hourly_rate` solo a admin.
- Separar endpoint `PATCH /users/me` (campos perfil) de endpoint admin para compensación.

---

### H-03) Riesgo de path traversal parcial en fallback SPA

Impacto:

- La comprobación de ruta usa `startswith` de string y puede aceptar rutas fuera de `dist` si comparten prefijo textual (`dist` vs `dist2`).

Evidencia:

- `/Users/david/Public/Código/the-agency/backend/main.py:251`

Fix recomendado:

- Sustituir por comparación robusta de paths:
  - `file_path.is_relative_to(_frontend_dist.resolve())` (Python 3.9+ usar fallback con `commonpath`).

---

### H-04) UX: pantallas en “Cargando...” indefinido cuando hay error de query

Impacto:

- Si la query falla y `data` queda `undefined`, la UI puede quedarse en estado de carga permanente sin fallback de error útil.

Evidencia (patrón):

- `/Users/david/Public/Código/the-agency/frontend/src/pages/holded-finance-page.tsx:125`
- `/Users/david/Public/Código/the-agency/frontend/src/pages/billing-page.tsx:63`
- `/Users/david/Public/Código/the-agency/frontend/src/pages/timesheet-page.tsx:144`

Fix recomendado:

1. Usar `isLoading`, `isError`, `error` de React Query explícitamente.
2. Mostrar estado de error accionable (`Reintentar`, mensaje de API normalizado).
3. Definir componente común `QueryState` para evitar divergencias entre pantallas.

## 5) Hallazgos medios

### M-01) Frontend lint con deuda estructural (26 errores)

Evidencia principal:

- `any` en componentes críticos.
- Reglas de pureza React (`Date.now()` en render, setState en effect).
- Dependencias de hooks no estables en Gantt.

Referencias:

- `/Users/david/Public/Código/the-agency/frontend/src/components/dashboard/overdue-tasks.tsx:35`
- `/Users/david/Public/Código/the-agency/frontend/src/components/gantt/gantt-chart.tsx:67`
- `/Users/david/Public/Código/the-agency/frontend/src/context/auth-context.tsx:30`
- `/Users/david/Public/Código/the-agency/frontend/src/pages/dashboard-page.tsx:166`

Fix recomendado:

- Objetivo inmediato: `npm run lint` en verde en CI.
- Priorizar eliminación de `any` y reglas `react-hooks/purity`/`set-state-in-effect`.

---

### M-02) Sin tests backend + entorno Python no reproducible

Evidencia:

- No se detectan tests backend.
- `backend/venv/bin/python` roto (`Library not loaded ... Python3`).

Referencia:

- `/Users/david/Public/Código/the-agency/backend/venv/bin/python`

Fix recomendado:

1. Crear suite mínima backend (auth, RBAC, rutas críticas de negocio).
2. Recrear venv con lock reproducible (`requirements-lock` o `uv`/`pip-tools`).
3. CI con `pytest` + smoke API.

---

### M-03) `client_health` con N+1 severo y lógica de coste no real

Impacto:

- `health-scores` escala mal con número de clientes.
- Coste estimado usa tarifa fija 40€/h, ignorando costes reales por usuario.

Evidencia:

- Bucle por cliente invocando múltiples queries:
  - `/Users/david/Public/Código/the-agency/backend/api/routes/clients.py:74`
- Servicio con varias queries por cliente:
  - `/Users/david/Public/Código/the-agency/backend/services/client_health.py:29`
  - `/Users/david/Public/Código/the-agency/backend/services/client_health.py:53`
  - `/Users/david/Public/Código/the-agency/backend/services/client_health.py:87`
- Tarifa fija:
  - `/Users/david/Public/Código/the-agency/backend/services/client_health.py:109`

Fix recomendado:

- Reescribir como agregaciones por lote (`group by`) y usar coste real (`TimeEntry * User.hourly_rate`).

---

### M-04) Listados Holded sin paginación

Impacto:

- Riesgo de latencia/uso de memoria alto cuando crezca la caché.

Evidencia:

- `/Users/david/Public/Código/the-agency/backend/api/routes/holded.py:329`
- `/Users/david/Public/Código/the-agency/backend/api/routes/holded.py:370`

Fix recomendado:

- Añadir `limit/offset` o cursor pagination y filtros indexados.

---

### M-05) Cliente API sin timeout global

Impacto:

- Requests colgados pueden degradar UX y dejar estados de carga atascados.

Evidencia:

- Axios sin `timeout`:
  - `/Users/david/Public/Código/the-agency/frontend/src/lib/api.ts:107`

Fix recomendado:

- Configurar timeout global (p.ej. 15s) + retries controlados en queries idempotentes.

---

### M-06) Login sin rate limiting dedicado ni bloqueo explícito por `is_active`

Impacto:

- Superficie de brute-force más amplia.
- Usuarios desactivados pueden obtener token, aunque luego fallen en rutas protegidas.

Evidencia:

- `/Users/david/Public/Código/the-agency/backend/api/routes/auth.py:14`
- `/Users/david/Public/Código/the-agency/backend/api/routes/auth.py:18`

Fix recomendado:

- Rate limit por IP/email para `/auth/login`.
- Verificar `is_active` en login y responder 401/403 consistente.

## 6) Oportunidades de optimización (rendimiento y mantenibilidad)

1. Estándar de autorización único:
- Declarar una matriz endpoint->permiso y validarla en tests.

2. Capa de errores homogénea:
- Contrato uniforme para integraciones externas (`reason_code`, `retryable`, `upstream_status`).

3. Frontend query states:
- Componente reutilizable `Loading/Error/Empty/Success` para evitar inconsistencias y “loading infinito”.

4. Tamaño de bundle:
- Build actual produce chunks grandes (`index ~413kB`, `BarChart ~349kB`).
- Mejorar lazy-loading de módulos de gráfica pesada y tablas complejas por ruta.

5. Consolidar clientes HTTP:
- Evitar instancias ad-hoc de axios por componente (ej. advisor cliente) y centralizar interceptores.

## 7) Plan de remediación sugerido

Fase 0 (24-48h):

1. Corregir RBAC write-bypass en mutaciones críticas.
2. Corregir flujo PDF propuestas (sin token query + authz correcta).
3. Corregir privacidad de dailys (`list/get` owner/admin).

Fase 1 (3-5 días):

1. Corregir bypass de permisos en contacts/resources/billing-events.
2. Bloquear edición de `hourly_rate` por no-admin.
3. Arreglar estados de error frontend en pantallas clave (holded, billing, timesheet, dashboard).

Fase 2 (1-2 semanas):

1. Lint en verde y reducción de `any`.
2. Test suite backend mínima (auth, RBAC, finanzas, dailys, proposals).
3. Optimización de `health-scores` y paginación Holded.

## 8) Conclusión

La base de producto es sólida y ya soporta un alcance funcional amplio, pero hay una brecha importante entre el modelo de permisos diseñado y su aplicación real en varios endpoints de escritura. Ese punto, junto con la exposición por token en URL y la privacidad de dailys, debe tratarse como prioridad de seguridad/operación inmediata.

Una vez cerrado ese bloque, el siguiente salto de calidad está en estabilidad UX (estados de error) y disciplina técnica (lint + tests backend + entorno reproducible).
