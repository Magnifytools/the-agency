# Search Console propio + bloque SEO en resúmenes mensuales

Decisión de David (18 oct 2026): The Agency importa Search Console por su
cuenta (no depende de `report-data` de The Engine, que tiene fallos: ver
findings.md). Los datos se guardan, así que se conservan más de 16 meses.

## Diseño

- **Conexión**: OAuth de Google a nivel de agencia (una cuenta con acceso a
  las propiedades de los clientes), scope `webmasters.readonly` + `openid email`
  para mostrar qué cuenta está conectada. La hace un admin desde Ajustes.
  Refresh token cifrado con `encrypt_vault_secret` (como Calendar).
  Redirect propio: `GSC_REDIRECT_URI` = `/api/gsc/callback`.
- **Propiedad**: `Client.gsc_url` (campo que ya existe y hoy nadie lee).
- **Tablas** (migración versionada `gsc_v1`):
  - `gsc_connection`: fila única; cuenta, token cifrado, quién y cuándo, estado.
  - `gsc_daily`: (site_url, date) → clicks, impressions, position. Por
    propiedad, no por cliente: si un cliente cambia de propiedad no se mezclan.
  - `gsc_site_sync`: por propiedad, último día con datos finales, último
    error, backfill hecho. Se usa para saber si un mes está completo.
- **Sync diario** (job `gsc`): primera vez, 16 meses de backfill; luego los
  últimos 7 días (GSC consolida con 2-3 días de retraso). Sólo datos finales.
- **Resumen mensual**: sólo si el periodo es un mes natural completo. El
  collector lee `gsc_daily` (BD propia, determinista, sin llamadas externas
  durante la generación). Mes vs mes anterior; y mismo mes del año anterior si
  hay datos. Clics e impresiones se suman; posición ponderada por impresiones.
  Si el mes no está completo o falta conexión, el bloque no se genera y el
  editor lo dice.
- **Redacción**: fuente `seo:search_console` (clase `seo`) admitida en
  `metrics`. Claude usa las cifras exactas y no atribuye causas.
- **Render**: tabla fija (no generada por IA) en email; una línea en
  Slack/Discord.
- **Editor**: panel con las cifras, aviso si faltan datos, y enlace a los
  informes de The Engine (`/p/{engine_project_id}/reports`) para generar y
  adjuntar el PDF (necesita login de The Engine: no va en el email).

## Pasos
1. Config + migración + modelos.
2. `services/gsc_service.py`: OAuth, sitios, consulta diaria, sync, resumen mensual.
3. `api/routes/gsc.py` + job en catálogo.
4. Collector + generator + renderer.
5. Frontend: Ajustes (conectar), ficha cliente (propiedad + estado), editor.
6. Tests (unit + integración Postgres) y e2e local.

## Fuera de alcance
- Datos por consulta/página (top keywords). Sólo totales diarios por propiedad.
- Bing y GA4.
