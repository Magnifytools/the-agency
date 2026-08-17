# Reducción de módulos — ago 2026

**Decisión de David (17 ago):** dejar visible solo lo que se usa de verdad. El resto
se **oculta, no se borra** — queda pendiente para más adelante. Alcance elegido:
"cero + casi cero". Profundidad: **interfaz Y backend** (desregistrar routers).

Origen: auditoría de ago 2026 (`tasks/archive/2026-08-17-audit-fixes/`).
279 de 349 endpoints sin una llamada en 77 días.

## Principio de diseño

**Un único interruptor por módulo**, no una lista por sitio. La lección de Vigil y
la de los 4 mapas de rentabilidad: si el estado vive en varios sitios, uno se queda
atrás. Aquí:

- `backend/core/modules.py` → `HIDDEN_MODULES`, sobreescribible por env
  `AGENCY_HIDDEN_MODULES` (reactivar en Railway sin desplegar).
- `frontend/src/lib/hidden-modules.ts` → la misma lista.
- Un test que compara ambas y **falla si divergen**.

Reactivar un módulo = quitar su clave de las dos listas (o de la env var).

## Lo que se queda visible

Dashboard · Clientes · Proyectos · Tareas · Inbox · Timesheet · Dailys · Digests ·
Equipo · Ajustes. Más el detalle de cliente y de proyecto (con menos pestañas).

## Módulos a ocultar y TODO lo que arrastra cada uno

| Clave | Nav | Rutas frontend | Routers backend | Además |
|---|---|---|---|---|
| `finance` | Finanzas | `/finance` + 7 subrutas | income, expenses, expense_categories, taxes, forecasts, advisor, bank_import, balance | — |
| `holded` | — | `/finance-holded` | holded | widget del dashboard |
| `cfo` | — | `/finance/cfo` | cfo | — |
| `reports` | Informes | `/reports` | reports | pestaña `informes` de cliente |
| `proposals` | Presupuestos | `/proposals` | proposals, proposals_crud, proposals_pdf, proposals_pricing, service_templates, investments | dashboard (`proposalsApi.list`) |
| `leads` | Pipeline | `/leads`, `/leads/:id`, `/pipeline` | leads | dashboard (`LeadFollowups`) |
| `growth` | Buffer | `/growth` | growth | pestaña Buffer de proyecto |
| `my_week` | Mi Semana | `/my-week` | my_week | — |
| `automations` | Automatizaciones | `/automations` | automations | — |
| `vault` | Vault | `/vault` | agency_vault | — |
| `billing` | Facturación | `/billing` | billing, billing_events | pestañas `facturacion` y `facturas` de cliente, pestaña facturación de proyecto |
| `capacity` | Capacidad | `/capacity` | — (usa clients/health-scores, que se queda) | — |
| `executive` | — | `/executive` | — (usa dashboard) | — |
| `discord` | Integraciones | `/discord` | discord | **OJO**: el envío de dailys a Discord vive en `dailys.py` y NO se toca. Solo se oculta la pantalla de configuración del webhook. |
| `communications` | — | — | communications | pestaña `comunicaciones` de cliente |
| `resources` | — | — | resources | pestaña `recursos` de cliente |
| `evidence` | — | — | evidence | pestaña evidencia de proyecto |
| `core_updates` | — | — | core_updates | — (y con él sobran sklearn+numpy, ~100 MB de imagen) |
| `invitations` | — | — | invitations | ninguno: no tiene NI UN llamador en el frontend |
| `export` | — | — | export | — |

## Excepción deliberada: `search` se queda

`/api/search` tiene 0 llamadas, pero no es un módulo con entrada de menú: es la
paleta ⌘K del *shell* de la aplicación. Desregistrarla dejaría el atajo roto dentro
de las páginas que sí conservamos, y son 88 líneas. Se queda, y se anota.
Lo mismo con `pm` (30 hits): el panel "Asistente PM" está en el dashboard.

## Riesgo principal

Desregistrar un router que use una pestaña de una página conservada. Mapeado ya
(grep de los `*Api.` del frontend): comunicaciones, facturación, recursos, informes
y facturas en el detalle de cliente; buffer, evidencia y facturación en el de
proyecto. Todas esas pestañas se ocultan a la vez que su router.

## Verificación exigida

1. `pytest` backend en verde, incluida integración con Postgres real.
2. `npx tsc --noEmit` limpio y `npm run build` OK.
3. Test nuevo: las dos listas de módulos coinciden.
4. Test nuevo: los routers ocultos NO están registrados y los del núcleo SÍ.
5. **Navegar la app de verdad** con el dev server: dashboard, cliente, proyecto,
   tareas, timesheet — sin errores de consola ni peticiones 404/500.
6. Comprobar que una ruta oculta redirige, no rompe.
