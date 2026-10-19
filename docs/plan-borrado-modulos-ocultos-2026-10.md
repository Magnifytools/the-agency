# Plan: borrar de verdad los módulos ocultos (fase 0 de Agency 2.0)

Fecha: 19-10-2026. Origen: `HIDDEN_MODULES` (`backend/core/modules.py` y
`frontend/src/lib/hidden-modules.ts`), módulos con 0 llamadas en 77 días.
Finanzas propias (`finance`, `holded`, income, expenses, taxes, forecasts,
tax_service, forecast_service) **no se tocan**.

## Reglas para cada PR

1. **Un módulo por PR**, de menor a mayor riesgo.
2. **Quitar la clave obliga a quitar sus puertas a la vez.** `is_enabled(x)` es
   `not is_hidden(x)`: si la clave sale de la lista y queda un
   `is_enabled("x")` / `isEnabled("x")`, devuelve `True` y la pantalla o el job
   vuelve a aparecer. Cada PR quita todas las comprobaciones de su clave.
3. **Los modelos y tablas se quedan.** El arranque exige las tablas de
   `schema_versions/p12.json` y los borrados duros de clientes
   (`clients.py:533-579`, `migrations.py:760-832`) borran filas de esas tablas.
   El borrado de tablas y enums va al final, en una migración versionada nueva
   (patrón `<x>_schema.py` + `MIGRATIONS`), cuando ya no quede ningún módulo.
4. Las listas de permisos (`users.py:_VALID_MODULES`, `users-page.tsx:ALL_MODULES`)
   cambian sólo si la clave de permiso deja de tener usos.
5. El servidor MCP y la extensión de Chrome no dependen de ninguno de estos
   módulos. Cuidado con `communication_schedules`, `manual_communications`,
   `scheduled_communications` y `weekly_report_service`: son el sistema de
   **entregas**, no el módulo `communications`.

## Orden propuesto

| # | Módulo | Riesgo | Qué se borra | Fuera del módulo | Tablas (migración final) |
|---|---|---|---|---|---|
| 1 | **core_updates** (PR abierta) | bajo | router `/api/engine/.../core-updates/analyze`, `core_update_service.py`, pestaña huérfana `core-updates-tab.tsx` | quita numpy y scikit-learn de `requirements.txt` | — |
| 2 | invitations | bajo | `routes/invitations.py`, `invitationsApi`, tipos | conservar `PermissionItem`/`UserPermissionsUpdate` de `schemas/invitation.py` (los usa `users.py`); `test_permission_write_serialization.py` importa a través del router | user_invitations |
| 3 | cfo | bajo | `routes/cfo.py`, `cfo-page.tsx`, `cfoApi` | una línea en `finance-tab-nav.tsx` (la pestaña CFO; nada más de finanzas) | — |
| 4 | vault | bajo | `routes/agency_vault.py`, `schemas/agency_asset.py`, `agency-vault-page.tsx` | conservar `encrypt/decrypt_vault_secret` y `VAULT_KEY` (los usan discord, gsc, calendar, entregas) | agency_assets |
| 5 | resources | bajo | `routes/resources.py`, `resource-list.tsx` | pestaña «Recursos» de la ficha de cliente | client_resources |
| 6 | evidence | bajo-medio | `routes/evidence.py`, `evidence-list.tsx`, `test_evidence.py` | pestaña de la ficha de proyecto; un test de `test_phantom_500_regression.py` | project_evidence |
| 7 | reports | medio | `routes/reports.py`, `report-archive`, `client-reports-tab` | pestaña «Informes»; clave de permiso `reports` | generated_reports |
| 8 | automations | medio-alto | `routes/automations.py`, `automations-page.tsx`, 5 ficheros de test | hooks `execute_automations` en `tasks.py`, `time_entries.py`, `projects.py` (×2); `_check_overdue_tasks` y el job `overdue_automations` de `job_catalog.py` (**obligatorio**: si no, el job se enciende) | automation_rules, automation_logs |
| 9 | communications | medio-alto | `routes/communications.py`, `communication-list.tsx` | `communication_logs` lo leen salud de cliente, digests (followups), insights PM, asesor de cliente y la línea de actividad | — (la tabla se sigue leyendo) |
| 10 | export | bajo técnico, **decisión** | `routes/export.py` (`/api/finance/export`), `financeExportApi` sin consumidores | lee Income/Expense/Tax: es finanzas | — |
| 11 | billing | alto | `routes/billing.py`, `billing_events.py`, `billing-page.tsx`, `billing-tab.tsx` | **zona gris**: `project-billing-tab.tsx` y los endpoints de `projects.py` (`billing-summary`, `invoice-tasks`, `mark-billed`) crean `Income`; la clave de permiso `billing` la usan también el asesor y la pestaña de facturas de Holded | billing_events |
| 12 | my_week | alto | `routes/my_week.py`, `schemas/my_week.py`, `my-week-page.tsx`, `myWeekKeys` | **antes, sacar los festivos** (ver abajo) | user_day_statuses (company_holidays se queda) |
| 13 | migración final | medio | modelos, enums y tablas de los módulos ya borrados | `clients.py`/`migrations.py` dejan de borrar filas de esas tablas; nueva versión de esquema | todas las de arriba |

Extra sin módulo: `beautifulsoup4` y `aiofiles` no se importan en ningún sitio.

## Festivos antes de borrar my_week

Hoy el CRUD de festivos vive en `my_week.py:536-591` (`/api/my-week/holidays`),
por eso el router está en `_CORE_ROUTERS` aunque la pantalla esté oculta. Lo usa
Ajustes → Festivos (`settings-page.tsx`).

Una PR propia, antes de la de my_week:

1. `backend/services/holidays.py`: `holidays_for(user, start, end)` (la lógica
   de my_week, que sí respeta `locality`) e `is_working_day`.
2. Router de núcleo `/api/holidays` con el CRUD; `settings-page.tsx` y sus tests
   pasan a usarlo. `_seed_national_holidays` se mueve al servicio.
3. `daily_reminders.is_working_day` y `scheduled_communications.plan_policy`
   usan el servicio. **Corrige un fallo**: hoy `is_working_day` ignora
   `locality` y trata como festivo el local de otro municipio de la misma
   comunidad (afecta al plan de mañana del equipo).
4. Aparte: `_seed_national_holidays` sólo trae los festivos móviles de 2026 y 2027.

## Qué necesita la decisión de David

- **export**: está en la lista de borrado, pero es la exportación CSV de
  finanzas (`/api/finance/export`). ¿Se borra ya o espera a Holded con el resto
  de finanzas?
- **billing**: ¿se va también la pestaña de facturación de proyecto y sus tres
  endpoints que crean `Income` («Marcar facturado»)? Si se quedan, la clave
  `billing` no puede desaparecer.
- **communications**: ¿salud de cliente, digests e insights siguen leyendo el
  histórico de `communication_logs` o se quitan esas lecturas?
