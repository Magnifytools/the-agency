# Plan de Remediación Total (Live Audit) - The Agency

Fecha de auditoría en vivo: 2026-03-05  
Entorno auditado: `https://agency.magnifytools.com`

## 1) Objetivo

Dejar la aplicación en estado "production-safe" para operación diaria, eliminando:

1. Fallos críticos (seguridad y errores 500).
2. Inconsistencias de permisos entre backend, frontend y navegación.
3. Bloqueos/estados de carga que degradan la experiencia.
4. Huecos funcionales para los 3 perfiles de uso: usuario operativo, coach financiero y project manager.

## Estado actualizado (verificación extra del 2026-03-05)

Tras una segunda pasada en vivo el mismo día:

1. `GET /api/inbox/count` ya responde `200` en admin y miembro.
2. `GET /api/vault/assets` ya responde `403` para miembro.
3. La prioridad cambia de \"apagar incendios\" a \"consolidar UX/permisos y cerrar política RBAC\".

Referencia de delta:

1. `/Users/david/Public/Código/the-agency/docs/auditoria-pasada6-live-delta-2026-03-05.md`

## 2) Evidencia base (auditoría live)

Artefactos de auditoría:

1. `/Users/david/Public/Código/output/playwright/agency-live-audit-2026-03-05/audit-report.json`
2. `/Users/david/Public/Código/output/playwright/agency-live-audit-2026-03-05/summary.json`
3. Evidencia visual RBAC: `/Users/david/Public/Código/output/playwright/agency-live-audit-2026-03-05/vault_member_5s.png`

Datos clave observados:

1. 30 rutas admin revisadas, 0 crashes de navegación, pero errores API/consola en múltiples rutas.
2. Error transversal: `GET /api/inbox/count` -> `500` (repetido en gran parte de la app).
3. Usuario miembro puede entrar por URL directa a vistas no visibles en menú.
4. Exposición grave: miembro accede a `/vault` y ve recursos internos.

## 3) Criterio de éxito global (Definition of Done)

La remediación se considera completada solo si se cumplen todos:

1. `GET /api/inbox/count` y `GET /api/inbox?status=pending,classified&limit=5` responden `2xx` en admin y miembro.
2. Ningún usuario miembro puede abrir por URL directa páginas admin o datos internos (Vault/gestión equipo).
3. Navegar por rutas no autorizadas muestra comportamiento consistente: redirección o pantalla 403, sin UI parcial rota.
4. Sin errores `500` en consola al recorrer rutas principales.
5. Smoke E2E de rutas admin/member en verde.

## 4) Backlog ejecutable por prioridad

## P0 - Bloque crítico (48 horas)

### P0-SEC-01: Cerrar fuga de datos en Vault (RBAC backend)

Problema:

1. `GET /api/vault/assets` permite `get_current_user` (cualquier autenticado), no `require_admin`.

Archivo:

1. `backend/api/routes/agency_vault.py`

Acción:

1. Cambiar `list_assets` a `Depends(require_admin)`.
2. Confirmar que `POST/PUT/DELETE` ya exigen admin (mantener).

Criterios de aceptación:

1. Miembro recibe `403` en `GET /api/vault/assets`.
2. Admin mantiene acceso completo CRUD.
3. Test backend específico agregado.

---

### P0-SEC-02: Guardas de permisos en frontend por ruta (no solo menú)

Problema:

1. El menú oculta rutas, pero el router permite abrirlas por URL directa.
2. Actualmente `ProtectedRoute` solo valida autenticación.

Archivos:

1. `frontend/src/components/layout/protected-route.tsx`
2. `frontend/src/App.tsx`
3. `frontend/src/context/auth-context.tsx`

Acción:

1. Crear guarda de autorización por ruta (ejemplo `PermissionRoute`) que soporte:
- `adminOnly`
- `module` + opcional `write`
2. Aplicar la guarda en rutas sensibles:
- Admin-only: `/vault`, `/users`, `/capacity`, `/discord`, `/executive`.
- Módulos: `/leads`, `/proposals`, `/reports`, `/billing`, `/finance/*`.
3. Comportamiento estándar para denegados: redirección a `/dashboard` con aviso o página `403` dedicada.

Criterios de aceptación:

1. Miembro no puede abrir URL directa de rutas fuera de permiso.
2. No aparece pantalla en estado parcial con spinner infinito por 403.
3. E2E member de rutas restringidas pasa.

---

### P0-API-01: Corregir error 500 transversal de Inbox

Problema:

1. `GET /api/inbox/count` devuelve `500` para admin y miembro.
2. Impacta Dashboard, Executive, Inbox, etc. (error transversal de shell).

Archivos de análisis/fix:

1. `backend/api/routes/inbox.py`
2. `backend/db/models.py` (modelo `InboxNote`, `InboxNoteStatus`)
3. Migraciones/alembic del módulo inbox (si aplica)

Diagnóstico obligatorio antes de parche:

1. Revisar logs backend productivos para stacktrace exacto de `inbox_count` y `list_inbox_notes`.
2. Verificar estado de tabla y enum en DB de producción:
- existe `inbox_notes`
- enum y valores esperados (`pending`, `classified`, `processed`, `dismissed`)
3. Validar que el usuario autenticado tenga consulta sin error en SQL directo.

Hardening mínimo a implementar:

1. Manejo de errores con logging estructurado en endpoints inbox.
2. Evitar que fallo de inbox rompa la shell global (frontend fallback en contador = 0).

Criterios de aceptación:

1. Ambos endpoints inbox responden `2xx` en admin y miembro.
2. No hay errores 500 en navegación base por causa inbox.
3. Test backend de regresión agregado.

---

### P0-SEC-03: Alinear protección backend para pantallas admin ocultas

Problema:

1. Algunas pantallas marcadas como admin en UI (`/users`, `/capacity`) siguen devolviendo datos por API a miembros.

Archivos candidatos:

1. `backend/api/routes/users.py`
2. `backend/api/routes/dashboard.py` (`/capacity`)

Acción (decisión de producto + seguridad):

1. Si son realmente admin-only, exigir `require_admin` en esos endpoints de página.
2. Si se necesita un subconjunto para miembros (p.ej. selectores), separar endpoint:
- endpoint mínimo para pickers (`id`, `full_name`)
- endpoint admin para vista completa.

Criterios de aceptación:

1. Miembro no consume datos de panel admin por URL directa.
2. No se rompe funcionalidad legítima de asignación en tareas/leads.

## P1 - Estabilización UX/Permisos (3-7 días)

### P1-UX-01: Manejo uniforme de 403/401 en frontend

Archivos:

1. `frontend/src/lib/api.ts`
2. `frontend/src/components/layout/app-layout.tsx`
3. Páginas de módulos restringidos (`executive`, `finance`, `reports`, etc.)

Acción:

1. Interceptor de respuesta para `401/403` con política única.
2. En queries críticas, evitar UI rota por respuestas prohibidas.
3. Introducir vista `403` reutilizable.

Criterios de aceptación:

1. En rutas sin permiso no hay spinner permanente ni paneles vacíos engañosos.
2. Mensaje de acceso denegado consistente en toda la app.

---

### P1-UX-02: Robustecer estado de carga (desktop + móvil)

Problema:

1. Durante varios segundos se ve pantalla oscura con spinner sin contexto.

Archivos:

1. `frontend/src/App.tsx` (fallback de `Suspense`)
2. `frontend/src/components/layout/app-layout.tsx`
3. Páginas con carga pesada (`finance-holded`, `timesheet`, `finance/taxes`, etc.)

Acción:

1. Sustituir spinner vacío por skeletons contextualizados por página.
2. Añadir timeout de carga con mensaje de problema de conexión y botón reintentar.
3. Mejorar perceived performance en móvil (primer contenido útil visible antes).

Criterios de aceptación:

1. No hay pantallas negras sin contexto > 2s.
2. Móvil muestra contenido útil inicial de forma estable.

---

### P1-UX-03: Evitar llamadas no necesarias desde shell global

Problema:

1. El layout llama APIs globales que pueden fallar y contaminar cualquier ruta.

Archivo:

1. `frontend/src/components/layout/app-layout.tsx`

Acción:

1. El contador inbox debe degradar a `0` y nunca bloquear UI.
2. Evitar toasts/errores repetitivos de polling global.
3. Consolidar observabilidad con log silencioso + telemetry.

## P2 - Evolución funcional (1-4 semanas)

### P2-FIN-01 (Coach financiero): pasar de "resumen" a "decisión"

Implementar:

1. Escenarios financiero: base/optimista/pesimista en previsiones.
2. Alertas accionables con umbral configurable (cash < X meses, margen < Y%).
3. Recomendación con impacto estimado (euros/mes y runway).
4. Checklist de cierre mensual guiado con estado persistente.

KPIs esperados:

1. Tiempo para decidir acción financiera < 5 min.
2. Runway siempre interpretable (sin estados ambiguos tipo solo "meses").

---

### P2-PM-01 (Project manager): control de riesgo operativo

Implementar:

1. Riesgo por tarea (sin responsable, sin fecha, sin estimación, vencida).
2. Dependencias y bloqueos entre tareas.
3. Vista de carga futura por semana/sprint y simulación de reasignación.
4. Salud por cliente/proyecto con trazabilidad de por qué cambia.

KPIs esperados:

1. Reducción de tareas sin responsable y vencidas semana a semana.

---

### P2-ONB-01: onboarding de "primer valor" en módulos vacíos

Módulos objetivo:

1. Reports
2. Proposals
3. Digests
4. Growth
5. News

Implementar:

1. Wizard en 2-3 pasos con CTA directo.
2. Semillas de datos opcionales de demo para arrancar flujo.

## 5) Plan de pruebas obligatorio

## Backend (pytest)

Añadir tests mínimos:

1. `member_forbidden_vault_read` -> 403.
2. `inbox_count_returns_200_for_admin_and_member`.
3. `inbox_list_status_filter_no_500`.
4. Si `/users` y `/capacity` pasan a admin-only: test 403 miembro.

## Frontend (Playwright)

Extender `frontend/e2e/frontend-smoke-2026-03-03.spec.ts` con:

1. Member URL guard matrix (`/vault`, `/users`, `/capacity`, `/executive`, `/finance*`, `/reports`, `/proposals`, `/billing`, `/leads`).
2. Assert de resultado esperado:
- redirect a `/dashboard` o página 403,
- nunca contenido sensible,
- nunca spinner infinito.
3. Assert de ausencia de `500` en endpoints inbox durante navegación base.

## Smoke manual final

1. Login admin y miembro.
2. Navegación de rutas principales.
3. Verificación de panel móvil (`/dashboard`) con carga estable.

## 6) Plan de despliegue y rollback

1. Deploy 1 (urgente): P0-SEC-01 + P0-API-01 + guardas frontend.
2. Monitoreo 24h:
- ratio 5xx,
- ratio 403 por ruta,
- errores JS de consola.
3. Deploy 2: P1 (UX/permisos uniforme).
4. Rollback automático si:
- sube 5xx > baseline,
- fallo de login/auth,
- regresión en rutas core (`/dashboard`, `/tasks`, `/projects`, `/finance`).

## 7) Checklist de entrega al cerrar

1. PR backend con fixes + tests verdes.
2. PR frontend con guardas + UX de errores/carga + E2E verdes.
3. Evidence post-fix con nueva auditoría Playwright y comparación de métricas.
4. Actualización de documentación funcional de permisos por rol.

---

## Anexo A - Rutas sensibles verificadas en auditoría de permisos (miembro)

1. `/vault` -> acceso visible a recursos internos (debe quedar bloqueado).
2. `/users` -> accesible por URL directa (debe seguir política definida, idealmente bloqueado en vista admin).
3. `/capacity` -> accesible por URL directa (alinear con política admin-only de UI).
4. `/executive`, `/finance/*`, `/reports`, `/proposals`, `/billing`, `/leads` -> actualmente abren página con datos parciales + múltiples 403.

## Anexo B - Endpoints con error transversal detectado

1. `GET /api/inbox/count` -> 500
2. `GET /api/inbox?status=pending,classified&limit=5` -> 500

## 8) Orden de ejecución recomendado (runbook)

Dia 1:

1. Aplicar `P0-SEC-01` (Vault backend admin-only).
2. Aplicar `P0-SEC-02` (guardas de permiso por ruta en frontend).
3. Ejecutar smoke member/admin enfocado en accesos directos.

Dia 2:

1. Diagnosticar y corregir `P0-API-01` (Inbox 500) con logs de producción.
2. Aplicar fallback seguro de contador inbox en shell global.
3. Cerrar `P0-SEC-03` (alinear `/users` y `/capacity` con política final).

Dia 3-5:

1. `P1-UX-01` + `P1-UX-02` + `P1-UX-03`.
2. Fortalecer E2E de permisos y regresión de errores API.

Comandos de validación sugeridos (en `frontend/`):

1. `npm run lint`
2. `npm run test`
3. `npm run build`
4. `npx playwright test e2e/frontend-smoke-2026-03-03.spec.ts --reporter=line --workers=1`
