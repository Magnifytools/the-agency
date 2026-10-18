# Hallazgos — bloque SEO en resúmenes mensuales

## Dónde encaja
- El informe mensual de `reports` está retirado a propósito (410 → "Prepara el
  resumen mensual del cliente desde Resúmenes"). Los digests ya tienen cadencia
  mensual (`ClientReportPolicy.cadence`).
- El digest tiene sección `metrics` (fuentes de clase `aggregate`). El bloque SEO
  va ahí con una fuente propia en `source_catalog` (kind `seo`): el editor ya
  pinta cualquier kind como chip sin cambios.
- `generate_locked_digest` llama al collector DOS veces y compara hashes
  (`sources_changed`), y no debe haber transacción abierta durante llamadas
  externas. La consulta a The Engine NO puede ir dentro del collector: va una
  vez, tras el `commit`, junto a la llamada a Claude.
- Vinculación: `Client.engine_project_id`. URL del front de The Engine:
  `ENGINE_FRONTEND_URL` + `/p/{id}/reports`.
- El PDF de The Engine exige login en The Engine (no hay enlace público): el
  enlace sirve al equipo en el editor, no al cliente en el email.

## Fuente de datos: problema
- `GET /integration/projects/{id}/report-data` (el que ya proxya The Agency) es
  el endpoint "legacy" que el contrato de integración deja fuera de garantías:
  - `except: pass` en las consultas de métricas → un fallo devuelve 0 clics
    sin error (al cliente le saldría −100 %).
  - Periodo anterior de 29 días frente a 30 del actual (sesgo ~3 %).
  - Posición = media simple, no ponderada por impresiones (regla global #8).
- `GET /integration/projects/{id}/summary` usa el RPC `agency_project_snapshot`
  (bien: suma, posición ponderada, falla explícito), y el RPC ya acepta
  `p_as_of`, pero el endpoint siempre pasa "hoy" y las ventanas son de 30 días
  fijos (no mes natural).
- GSC llega con 2-3 días de retraso: un resumen de septiembre generado el 1 de
  octubre tendría los últimos días incompletos.
