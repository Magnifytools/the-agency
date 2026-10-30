# Fase 1 · Cartera de clientes y estado del cliente

Plan Agency 2.0 (fase 1, mejoras 3, 4 y parte de 7). Decisión de David
(19 oct 2026): la salud deja de leer el histórico de comunicaciones.

## Qué cambia

La salud 0-100 (5 factores ponderados; rentabilidad siempre vacía porque
depende de finanzas, oculto; comunicaciones sin uso) se sustituye por un
**estado explicado** por cliente: `ok` (Bien) · `watch` (Vigilar) · `act`
(Actuar) · `no_data`, con la lista de motivos. Cinco señales vivas:

| Señal | Fuente | Vigilar | Actuar |
|---|---|---|---|
| Tráfico SEO (28 días vs 28 anteriores) | `gsc_daily` propio si hay propiedad; si no, summary de Engine | baja > 5 % | caída ≥ umbral (20 %) con base ≥ 100 clics (mismo criterio que el semáforo) |
| Resumen | `ClientReportPolicy` + último `WeeklyDigest` enviado | toca (periodo cerrado, ≤ 5 días) | atrasado (> 5 días) |
| Tareas vencidas | tareas abiertas con fecha pasada | 1-2 | ≥ 3 |
| Esperando al cliente | tareas en espera; seguimiento vencido | seguimiento vencido | — |
| Horas del mes vs cuota (sólo admin) | horas × tarifa / Σ `monthly_fee` activos (fallback `monthly_budget`) | ≥ 90 % | ≥ 110 % |

Sin ninguna señal medida → `no_data`. Cada señal sólo se calcula si quien mira
puede leer su fuente (módulos tasks, digests, timesheet; consumo sólo admin).

## Piezas
1. `backend/services/client_status.py` + `GET /api/clients/portfolio` y
   `GET /api/clients/{id}/status`. Se borran `client_health.py`,
   `/health-scores` y `/{id}/health`.
2. Frontend: la lista de clientes muestra la cartera (estado + motivos,
   tráfico, horas/consumo, último resumen, en espera, vencidas), ordenable por
   estado. La ficha cambia el bloque de salud por el de estado (el rediseño en
   4 bloques es otra pieza).
3. Tests unit + integración Postgres; verificación visual.

## Fuera
- Ficha en 4 bloques (siguiente pieza, reutiliza este estado).
- Ciclo mensual de resúmenes (sesión aparte).
