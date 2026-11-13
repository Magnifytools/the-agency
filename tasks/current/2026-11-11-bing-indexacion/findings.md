# Hallazgos

## API de Bing Webmaster (Microsoft Learn, consultado 11 nov 2026)
- Acceso: OAuth 2.0 (recomendado) o **API key**. La clave es **por usuario, no
  por sitio**: una clave sirve para todos los sitios verificados de esa cuenta de
  Microsoft. Una sola clave por usuario; borrarla invalida todo lo que la use.
- Formato JSON: `https://ssl.bing.com/webmaster/api.svc/json/<Método>?apikey=<clave>&siteUrl=…`.
  Respuesta envuelta en `{"d": …}`; fechas `/Date(1699999999000)/`.
  **Confirmar con una llamada real antes de escribir el parser.**
- `GetUrlInfo(siteUrl, url)` → `UrlInfo`: `Url`, `HttpStatus`, `LastCrawledDate`,
  `DiscoveryDate`, `IsPage`, `DocumentSize`, `AnchorCount`, `TotalChildUrlCount`.
  Pendiente de confirmar qué devuelve para una URL que Bing no conoce (¿error?,
  ¿ceros y fecha mínima?): de eso depende el estado `unknown`.
- `GetPageStats(siteUrl)` → lista de `QueryStats` (`Query` = la página, `Date`,
  `Impressions`, `Clicks`, `AvgImpressionPosition`, `AvgClickPosition`).
  Es el informe de rendimiento por página. Granularidad de `Date` (¿semanal?)
  a confirmar.
- `GetPageQueryStats(siteUrl, page)` → consultas de una página (mismo tipo).
- `GetUserSites()` → sitios de la cuenta (para validar la clave y casar el
  cliente con su sitio).
- Otros útiles más adelante: `GetCrawlIssues`, `GetCrawlStats`,
  `GetUrlSubmissionQuota`, `SubmitUrl`/`SubmitUrlBatch`, `GetUrlTrafficInfo`.
- **AI Performance** (citas en Copilot, vista previa desde el 10 feb 2026): no
  consta en la API. Sólo en la web de Bing Webmaster Tools.
- Cuota: MJ avisa de que todas las llamadas cuentan contra la cuota de la
  propiedad. Por eso la comprobación es a mano (POST) y con tope de URLs.

## Piezas de The Agency que se reutilizan
- `services/gsc_live.py` + `api/routes/client_gsc.py`: patrón "en vivo, sin
  guardar", errores `{"code","message"}`, limitador por persona, mismo 404.
  `_domain` / `_belongs` para casar sitio y cliente.
- `core/security.encrypt_vault_secret` / `decrypt_vault_secret` + CHECK `v1:%`
  (como el webhook de Slack y Accesos).
- `web_watches` (URLs vigiladas, `is_active`, `archived_at`): la lista de URLs
  clave ya existe por cliente.
- `normalize_site_url` para cruzar URLs con las de Bing.
- Tests con `httpx.MockTransport`: `test_web_health.py`, `test_web_uptime.py`.
- Control SEO: `components/clients/seo-control/seo-control-tab.tsx` (cards).
- Ajustes: `components/settings/search-console-section.tsx` como modelo.
- `services/web/sitemap.py` ignora `lastmod` a propósito (poco fiable): no se
  compara rastreo con `lastmod` en la fase 1.

## Cuentas de Bing (David, 11 nov 2026)
- Cada web tiene su propia cuenta de Bing Webmaster Tools: la clave se conecta
  cliente a cliente (`client_bing_connections`), no como `gsc_connection`.
  Dos clientes que compartan cuenta guardarían la misma clave dos veces: se
  acepta, es lo raro.
- Como la cuenta puede ver más de un sitio, al conectar se elige cuál es el del
  cliente (preseleccionado por dominio) y se guarda en `site_url`.
