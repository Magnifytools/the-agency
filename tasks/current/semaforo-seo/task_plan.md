# Semáforo SEO por cliente

Objetivo: ver de un vistazo qué clientes suben o bajan de tráfico orgánico y
abrir una incidencia cuando uno activo cae por encima de un umbral.

## Decisión de datos (paso 1)
- The Engine (`/api/integration/projects/{id}/summary`) YA devuelve
  `clicks_previous_30d` e `impressions_previous_30d` (ventana `previous_period_start`
  = as_of-59 … period_start-1), sumados en la ventana.
- The Agency ya guarda ese summary entero en `clients.engine_summary_data`.
- Conclusión: NO hace falta snapshot nuevo ni columnas. La variación se deriva
  del summary sincronizado. Posición anterior no viene en el summary → no se
  compara posición (no se inventa).

## Pasos
1. `backend/services/seo_traffic.py`: función pura `seo_traffic_trend(summary)`
   → clics/impresiones actuales y anteriores, % variación, estado
   (`up`/`stable`/`down`/`drop_alert`). Umbrales en `config.py`:
   `SEO_DROP_ALERT_PCT` (20) y `SEO_DROP_MIN_CLICKS` (100 clics en el periodo anterior).
2. `ClientResponse`: campos calculados `seo_clicks_change_pct`, `seo_trend`.
3. Incidencia `client_seo_traffic_drop` (entity_type `client`) en el
   reconciliador de incidentes existente: destinatarios = admins + responsables de
   proyectos activos/planificados del cliente con lectura de `clients`.
   Clave `...:open` → se resuelve sola cuando el tráfico se recupera; descartar
   no reabre mientras siga la caída.
4. Frontend: columna "Tráfico SEO" ordenable en la lista de clientes (asc = los
   que más caen primero) + ▲/▼ en el widget de Engine del detalle.
5. Tests: unitarios de la función, integración Postgres del collector + cláusula
   de visibilidad, vitest del badge. Verificación visual.
