# Auditoría Pasada 6 (Live Delta) - 2026-03-05

Entorno: `https://agency.magnifytools.com`  
Tipo: segunda pasada de verificación en vivo (comparativa contra pasada anterior del mismo día).

## Resumen corto

Estado actual: mejora clara frente a la pasada anterior.

1. **Inbox 500**: no reproducible en esta pasada.
2. **Fuga de Vault para miembro**: cerrada (`403 Admin required`).
3. **Rutas restringidas de miembro**: ahora no cargan la vista sensible; redirigen a dashboard.
4. Aún quedan ajustes de UX/permisos y consistencia de política RBAC.

## Evidencia generada

1. `/Users/david/Public/Código/output/playwright/agency-live-audit-pass2-2026-03-05/audit-pass2-report.json`
2. `/Users/david/Public/Código/output/playwright/agency-live-audit-pass2-2026-03-05/audit-pass2-summary.json`

## Resultados cuantitativos (pasada 2)

1. `adminTotalRoutes`: 30
2. `adminRoutesWith500`: 0
3. `adminRoutesWith403`: 0
4. `adminRoutesNotReadyUnder12s`: 1 (`/clients/5` por 404 funcional)
5. `memberTotalRestrictedRoutes`: 16
6. `memberBlockedPartial`: 16
7. `mobileDashboardReadyMs`: 1067ms

## Validaciones directas clave

### Inbox (antes: 500 global)

Ahora:

1. `GET /api/inbox/count` -> `200` (admin y miembro)
2. `GET /api/inbox?status=pending,classified&limit=5` -> `200` (admin y miembro)

### Vault (antes: leak crítico)

Ahora:

1. `GET /api/vault/assets` con miembro -> `403` (`Admin required`)
2. Confirmado también por navegación UI: ya no se ve contenido sensible.

## Qué sigue pendiente

## P1 - UX de denegación de acceso (mejorable)

Síntoma:

1. En rutas restringidas para miembro (`/executive`, `/finance/*`, `/leads`, `/reports`, etc.) no aparece una pantalla 403 dedicada.
2. Se redirige a dashboard, pero durante la transición se generan varias llamadas `403` (ruido técnico y experiencia poco limpia).

Recomendación:

1. Implementar pantalla/estado de acceso denegado explícito.
2. Reducir llamadas innecesarias al entrar a rutas no permitidas.

## P1 - Política RBAC no totalmente alineada (UI vs API)

Observado en miembro (API directa):

1. `GET /api/users` -> `200` (respuesta saneada: id + full_name)
2. `GET /api/dashboard/capacity` -> `200`

Esto puede ser correcto si es decisión funcional, pero hoy contradice la señal de UI (rutas admin ocultas).

Recomendación:

1. Definir política explícita:
- O bien admin-only real para esos datos.
- O bien mantener lectura limitada para miembros y documentarlo formalmente.
2. Si se mantiene, separar endpoint "picker" del endpoint "admin panel" para evitar ambigüedad.

## P2 - Limpieza funcional de pruebas de detalle

1. `/clients/5` dio `404` (cliente no encontrado). Es más un issue de dataset/seed de pruebas que un bug general.
2. Conviene estabilizar IDs de prueba o resolver dinámicamente IDs válidos en E2E.

## Delta de prioridad frente al plan anterior

Cambios de estado:

1. `P0-API-01 (Inbox 500)` -> **aparentemente resuelto en producción** (mantener monitoreo 24-48h).
2. `P0-SEC-01 (Vault leak)` -> **resuelto**.
3. `P0-SEC-02 (guardas frontend)` -> **parcialmente resuelto** (bloquea, pero UX de 403 todavía mejorable).

Pendiente principal ahora:

1. Consolidar UX de denegación + reducir ruido de 403.
2. Cerrar decisión de RBAC para `/users` y `/dashboard/capacity`.
3. Fortalecer E2E de permisos y rutas con IDs dinámicos.

## Checklist de cierre recomendado

1. Añadir test E2E: miembro no ve contenido sensible en todas las rutas restringidas.
2. Añadir test backend: vault read member = 403.
3. Añadir test API policy para users/capacity según decisión final.
4. Ejecutar una pasada final de auditoría live post-ajuste UX 403.

