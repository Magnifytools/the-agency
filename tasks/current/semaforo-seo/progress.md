# Progreso
- [x] Investigación: Engine ya da periodo anterior (ver task_plan) → sin columnas nuevas
- [x] Backend: seo_traffic.py, campos calculados en ClientResponse, sort servidor en GET /api/clients
- [x] Incidencia client_seo_traffic_drop en el reconciliador (umbral por env)
- [x] Frontend: columna "Tráfico SEO" ordenable + ▲/▼ en widget Engine
- [x] Tests: unitarios (seo_traffic, ClientResponse) + 5 de integración Postgres; vitest badge; suites completas
- [x] Verificación visual en BD desechable (the_agency_seo_preview, borrada al acabar)
- [ ] PR

## Hallazgos
- El dev DB local `the_agency` tiene historia Alembic que `backend.scripts.migrate`
  no adopta ("Unsupported Alembic history"): para previsualizar hay que usar una BD
  vacía migrada + datos de ejemplo.
- La lista de clientes pagina de 25; con 28 activos un orden sólo en cliente no
  bastaba → orden en servidor.
