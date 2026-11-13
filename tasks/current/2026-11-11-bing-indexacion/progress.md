# Progreso

## 11 nov 2026
- Plan de la fase 1 escrito (`task_plan.md`).
- David: cada web tiene su propia cuenta de Bing → conexión por cliente.
- **Fase 1 implementada** en la rama `feat/bing-indexacion` (PR abierta el 11 nov):
  - Migración `client_bing_v1` (`client_bing_connections`), modelo, servicio
    `services/bing_live.py`, rutas `api/routes/client_bing.py`, limitador.
  - Ajustes del cliente: `client-bing-card.tsx`. Control SEO: `seo-bing-card.tsx`.
  - `/privacidad` (ES/EN) y sección en `the-agency/CLAUDE.md`.
  - Tests: `test_bing_live.py` (33), `test_client_bing_schema.py` (6, Postgres),
    `seo-bing-card.test.tsx`, `client-bing-card.test.tsx`, privacidad.
  - Visto en el navegador con Bing simulado (BD de prueba aparte, ya borrada):
    clave errónea, conexión con sitio preseleccionado, comprobación, consultas
    de una URL, móvil (la tabla se desplaza en horizontal).
- Comprobado contra Bing real sin clave: error `{"ErrorCode":3,"Message":"ERROR!!! InvalidApiKey"}` con HTTP 400.
- **Falta**: prueba con la clave real de una web (formato de `GetUrlInfo` para
  una URL desconocida, granularidad de `Date` y escala de `AvgImpressionPosition`).
- La BD local de desarrollo (`the_agency`) no arranca con el backend actual: no
  tiene `agency_schema_versions` (historia de Alembic antigua, "explicit adoption
  is required"). No es de este cambio.
