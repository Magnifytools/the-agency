# Saltar el periodo de un resumen (sugerencia #5 de Nacho)

> "Poder eliminar resúmenes pendientes, que porque no se hagan ya o porque esté
> de vacaciones no se tramiten." — Nacho, 26 oct 2026.

Decisión de David (16 nov 2026): **saltar ese periodo** (cliente + periodo).
No borrar borradores: el periodo seguiría pendiente.

## Qué es "saltado"
- Tabla `digest_period_skips` (migración `digest_period_skips_v1`): cliente,
  `period_start`/`period_end` (un periodo válido: semana lunes-domingo o mes
  natural, `period_cadence`), `reason` (1–300), `skipped_by`, `skipped_at`.
  Única por (cliente, periodo).
- Saltar = el periodo deja de estar pendiente: ni `report_pending` ni
  `report_unsent`, fuera del recuento de "sin entregar" de la fila Operación,
  no cuenta en contra en el estado del cliente y "Para entregar" lo enseña como
  "Saltado" con quién, cuándo y por qué.
- NO entrega trabajo: "listo para entregar" (`_ready_to_deliver`) no cambia.
- Deshacer = "Volver a pendiente" (borra la fila). Fuera del journal ⌘Z: la
  fila tiene su propio botón y el toast ofrece deshacer.

## Permisos
- Saltar / volver: escritura de `digests` y ser admin o responsable actual del
  cliente (las reglas de `authorize_digest`). Sólo periodos cerrados
  (`period_end` < hoy). 409 si el periodo ya tiene entrega confirmada.

## Dónde se engancha
1. `incident_report_conditions.py`: `delivery_confirmed_clause` → incluye el
   salto (lo usan `report_unsent`, su visibilidad y `unsent_monthly_clients`
   → fila Operación). `report_pending`: colector y `pending_live`.
2. `client_status._digests`: el salto cuenta como último periodo cubierto.
3. `report_policy.preview_items`: estado `skipped` + `skip` en la fila.
4. API `POST/DELETE /api/digests/period-skips`.
5. Front `digest-monthly-cycle.tsx`: "Saltar este periodo" (diálogo con
   motivo) y "Volver a pendiente".

## Tests
- Integración: esquema; saltar quita `report_pending`/`report_unsent`, la
  fila Operación y el estado; permisos; 409 entregado; volver a pendiente.
- Front: diálogo, estado Saltado, volver.
