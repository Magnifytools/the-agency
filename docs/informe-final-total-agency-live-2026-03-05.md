# Informe Final Total - Auditoría Live de The Agency (2026-03-05)

Entorno auditado: `https://agency.magnifytools.com`  
Fecha de consolidación: 2026-03-05

## 1) Alcance total ejecutado

Se realizaron 3 pasadas en vivo, con validación técnica y funcional real:

1. Pasada 1: barrido completo de rutas, detección de fallos críticos iniciales.
2. Pasada 2: verificación delta para confirmar si los críticos seguían activos.
3. Pasada 3: auditoría profunda de flujos, permisos, API matrix, rendimiento percibido y móvil.

Cobertura acumulada:

1. Rutas admin auditadas en profundidad: 31.
2. Rutas member auditadas (incluyendo restringidas): 24.
3. Matriz de endpoints críticos por rol (admin/member).
4. Flujos de mutación validados con limpieza:
- Inbox create/delete (con CSRF).
- Task create/get/delete (con CSRF).
5. Verificación móvil real (iPhone 13) en rutas clave.

## 2) Estado actual consolidado (hoy)

Conclusión ejecutiva:

1. La app ya no está en estado crítico operativo.
2. Los problemas más graves detectados al inicio del día se han corregido en producción.
3. Queda trabajo de consolidación UX/RBAC y de evolución de producto (finanzas + PM).

Resultado global recomendado:

1. Estabilidad técnica actual: alta.
2. Seguridad de acceso crítico: alta (con un punto de política pendiente).
3. UX de permisos: media (funciona, pero mejorable).
4. Potencia de negocio para toma de decisiones: media-alta, con margen claro de mejora.

## 3) Qué estaba mal y qué ya está resuelto

## Resuelto

### R-01: Error transversal de Inbox (500)

Antes:

1. `GET /api/inbox/count` devolvía `500` y contaminaba múltiples pantallas.

Ahora (pasada 3):

1. `GET /api/inbox/count` -> `200` (admin y member).
2. `GET /api/inbox?status=pending,classified&limit=5` -> `200` (admin y member).

### R-02: Fuga crítica de Vault para miembro

Antes:

1. Usuario member podía acceder a `/vault` y ver recursos internos.

Ahora:

1. `GET /api/vault/assets` para member -> `403` (`Admin required`).
2. Navegación de member a `/vault` redirige a dashboard (sin exponer contenido sensible).

### R-03: Rutas restringidas por URL directa

Antes:

1. Member podía abrir varias rutas fuera de su scope con UI parcial y datos mezclados.

Ahora:

1. En 16/16 rutas restringidas auditadas, member acaba redirigido a dashboard.
2. No se observó render de contenido sensible en esas rutas.

## 4) Hallazgos pendientes (abiertos)

## P1-01: UX de denegación mejorable

Estado:

1. El bloqueo funciona, pero el patrón actual es redirección a dashboard con ruido de llamadas 403 durante transición.

Impacto:

1. Experiencia menos clara para usuario.
2. Ruido técnico en telemetría y debugging.

Acción:

1. Implementar vista 403 explícita y silenciosa.
2. Cortar queries de páginas restringidas antes de montar componentes.

## P1-02: Política RBAC no 100% cerrada en dos APIs

Estado observado con member:

1. `/api/users?page=1&page_size=5` -> `200` con datos sanitizados.
2. `/api/dashboard/capacity` -> `200`.

Esto puede ser válido por diseño, pero debe decidirse explícitamente y documentarse.

Acción:

1. Decidir política oficial:
- opción A: admin-only real,
- opción B: lectura limitada para miembros.
2. Si opción B, separar endpoint "picker" y endpoint "panel admin".

## P1-03: Cobertura E2E de permisos aún mejorable

Estado:

1. Hay cobertura smoke, pero faltan aserciones más estrictas de no-exposición por URL directa en todos los módulos sensibles.

Acción:

1. Añadir matriz de permisos por ruta en E2E con expected behavior exacto por rol.

## 5) Evaluación funcional por perfil (lo que pediste: usuario + coach financiero + PM)

## 5.1 Usuario operativo diario

Cumple bien:

1. Dashboard útil con KPIs y foco operativo.
2. Navegación principal clara.
3. Módulos clave accesibles y estables (clientes, proyectos, tareas, timesheet, inbox).

A mejorar:

1. Mensajería de acceso denegado más clara (no solo redirección).
2. Estados vacíos con onboarding de primer valor más guiado.
3. Menos fricción percibida en cargas iniciales.

## 5.2 Coach financiero

Cumple bien:

1. Base sólida: dashboard financiero, ingresos, gastos, impuestos, previsiones, asesor.
2. Capa Holded separada y operativa.

A mejorar:

1. Pasar de “lectura de datos” a “decisión asistida”.
2. Escenarios (base/optimista/pesimista) y recomendaciones con impacto cuantificado.
3. Alertas por umbral con acciones propuestas (caja, margen, runway, impuestos).

## 5.3 Project manager

Cumple bien:

1. Flujo general de control de tareas/proyectos/leads/dailys.
2. Estructura apta para seguimiento continuo.

A mejorar:

1. Riesgo predictivo (bloqueos, dependencias, retrasos).
2. Simulación de carga futura y sugerencias de reasignación.
3. Trazabilidad de salud por cliente/proyecto con explicación de variación.

## 6) Validaciones técnicas profundas (pasada 3)

## Seguridad y sesión

1. CSRF activo y funcionando.
2. Mutaciones sin token válido devuelven `403`.
3. Mutaciones con token válido funcionan.

Pruebas reales ejecutadas:

1. Inbox create/delete con CSRF: OK + cleanup.
2. Task create/get/delete con CSRF: OK + cleanup.

## Rendimiento percibido

Admin (31 rutas):

1. 0 rutas sin render útil bajo 15s.
2. Rutas más lentas por tiempo a contenido útil: `/capacity`, `/clients/:id`, `/finance/*` (aún en rango razonable).

Móvil (5 rutas):

1. 0 rutas sin render útil bajo 15s.
2. Dashboard móvil listo en ~1.4s en esta pasada.

## Estabilidad

1. Admin: 0 rutas con `4xx/5xx` durante barrido de pasadas de ruta.
2. Admin: 0 errores de consola en barrido principal de pasada 3.

## 7) Backlog final consolidado para desarrollo

## P0 (cierre rápido final)

1. Cerrar decisión RBAC de `/api/users` y `/api/dashboard/capacity` y reflejarla en código + tests.
2. Congelar contrato de permisos por rol en documento técnico único.

## P1 (estabilización UX/permisos)

1. Crear `AccessDeniedPage` y usarla en rutas restringidas.
2. Evitar montaje de queries cuando la ruta no está autorizada.
3. Homogeneizar manejo `401/403` en `api.ts` + guardas de ruta.
4. Completar E2E matriz de permisos (admin/member) y hacerlo gating en CI.

## P2 (producto: valor alto)

1. Finanzas:
- escenarios, alertas accionables, recomendaciones con impacto.
2. PM:
- motor de riesgo, dependencias, simulación de carga.
3. Onboarding:
- wizard de primer valor en módulos vacíos (`reports`, `proposals`, `digests`, `growth`, `news`).

## 8) Plan de pruebas definitivo

## Backend

1. `member_forbidden_vault_read`.
2. `inbox_count_admin_member_200`.
3. `inbox_create_delete_with_csrf`.
4. `task_create_delete_with_csrf`.
5. Tests de política final para users/capacity según decisión.

## Frontend E2E

1. Matriz member URL directa en rutas restringidas.
2. Assert de no exposición de contenido sensible.
3. Assert de comportamiento uniforme (403 page o redirect explícito).
4. Smoke admin de rutas core.
5. Smoke móvil de dashboard/clientes/proyectos/tareas/finanzas.

## Observabilidad

1. Alertas por ratio `5xx`.
2. Alertas por incremento de `403` inesperado por ruta.
3. Dashboard de errores frontend (console/pageerror) por release.

## 9) Riesgos remanentes

1. Ambigüedad de política RBAC si no se cierra explícitamente en esta iteración.
2. Si solo se redirige y no se muestra 403 claro, el usuario no entiende por qué no entra.
3. Sin E2E de permisos como gating, puede reaparecer fuga por regresión.

## 10) Recomendación de ejecución (orden exacto)

1. Día 1:
- cerrar política RBAC users/capacity,
- implementar AccessDeniedPage,
- ajustar guardas para cortar llamadas innecesarias.
2. Día 2:
- ampliar E2E de permisos + smoke móvil,
- activar gating CI.
3. Día 3-5:
- iniciar P2 de finanzas y PM (valor negocio).

## 11) Archivos de referencia (fuente consolidada)

Documentos previos y deltas:

1. `/Users/david/Public/Código/the-agency/docs/plan-remediacion-total-live-2026-03-05.md`
2. `/Users/david/Public/Código/the-agency/docs/auditoria-pasada6-live-delta-2026-03-05.md`

Artefactos de auditoría:

1. `/Users/david/Public/Código/output/playwright/agency-live-audit-2026-03-05/audit-report.json`
2. `/Users/david/Public/Código/output/playwright/agency-live-audit-pass2-2026-03-05/audit-pass2-report.json`
3. `/Users/david/Public/Código/output/playwright/agency-live-audit-pass3-2026-03-05/audit-pass3-report.json`

## 12) Cierre

Estado final del día:

1. La app está operativa y mucho más robusta que al inicio de la auditoría.
2. Los críticos principales han sido cerrados.
3. Queda una última capa de consolidación UX/RBAC y luego foco en evolución de producto.

