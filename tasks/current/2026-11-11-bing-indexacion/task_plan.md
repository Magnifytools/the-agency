# Bing: indexación y posición de las URLs clave del cliente

> Origen: hilo de MJ Cachón (10 nov 2026, herramienta `bing-inspector`) y
> comentario de Nacho: "hacer lectura de indexación (y posicionamiento de 10
> URLs por ejemplo) para saber si pueden estarnos teniendo en cuenta la IA en ese
> primer paso de aparecer en Bing".

## Para qué

ChatGPT y Copilot sacan candidatos de los resultados de Bing antes de elegir
qué citar. Una URL que Bing no ha rastreado (o que rastreó hace meses) difícilmente
entra en ese primer paso. Queremos verlo por cliente sin ir URL a URL en Bing
Webmaster Tools.

**Lo que NO afirma**: que estar en Bing haga que la IA te cite. Es un requisito
para entrar, no una medida de visibilidad en IA. La interfaz lo dice así.

## Decisiones de partida (a confirmar por David)

1. **Qué URLs**: las URLs vigiladas activas (no archivadas) del cliente
   (`web_watches`); sin ninguna, la home (`Client.website`). Máx. 25 por
   comprobación. No se crea una lista nueva de "URLs clave": ya existe.
2. **Dónde**: tarjeta "Bing" en la pestaña Control SEO (lectura de `clients`).
3. **Fase 1 en vivo, sin guardar datos**: botón "Comprobar en Bing"; lo único
   guardado es la clave de la API (cifrada). Como Search Console en vivo.
4. **Fuera de la fase 1**: job diario, histórico, avisos en la campana, pedir
   indexación (`SubmitUrl` / IndexNow), MCP, IA y el `lastmod` del sitemap
   (`services/web/sitemap.py` lo ignora a propósito por poco fiable).

## Fase 1: pasos

### 1. Conexión POR CLIENTE (cada web tiene su propia cuenta de Bing)
Decisión de David (11 nov 2026): cada web tiene una cuenta de Microsoft/Bing
propia, así que la clave se conecta cliente a cliente, no en Ajustes globales.
- [ ] Migración `client_bing_v1` (contrato JSON + `startup/client_bing_schema.py`
      + al final de `MIGRATIONS`): tabla `client_bing_connections`, PK
      `client_id` (FK a `clients`, en cascada): `api_key` (Text, CHECK
      `LIKE 'v1:%'`, cifrada con `encrypt_vault_secret`), `site_url` (el sitio
      de Bing elegido; lo leen todas las llamadas), `status` `ok|invalid`,
      `last_error`, `connected_by`, `connected_at`. Una fila por cliente.
- [ ] `api/routes/client_bing.py`, conexión (sólo admin, como el Slack del
      cliente, porque guarda un secreto):
      - `GET /api/clients/{id}/bing/connection`: `{connected, site_url, status,
        connected_by_name, connected_at}`; nunca la clave. Lectura de `clients`.
      - `POST /api/clients/{id}/bing/connection/sites` `{api_key}`: llama a
        `GetUserSites` SIN guardar y devuelve los sitios de esa cuenta, con el
        que casa con la web del cliente marcado (`_domain`/`_belongs` de
        `gsc_live`, sacados a un helper común). 422 `invalid_key` si Bing la rechaza.
      - `PUT /api/clients/{id}/bing/connection` `{api_key, site_url}`: vuelve a
        comprobar que la cuenta ve `site_url` y guarda. Sustituye la anterior.
      - `DELETE /api/clients/{id}/bing/connection`: borra la fila (en Bing no
        hay nada que revocar; se dice que la clave sigue viva allí).
- [ ] UI en Ajustes del cliente (`components/clients/client-bing-card.tsx`, junto
      a Search Console/GA4): pegar la clave → "Comprobar" → elegir el sitio
      (preseleccionado el que casa; si sólo hay uno, directo) → "Conectar".
      Conectado: sitio, quién y cuándo, "Cambiar clave" y "Desconectar". Con
      el paso a paso para sacar la clave (Bing Webmaster Tools → Ajustes →
      API access → API Key). Sólo admin edita; el resto ve el estado.
- [ ] Fuera del Deshacer (guarda un secreto, como Accesos y el Slack del
      cliente). Test que lo vigile.

### 2. Servicio en vivo (`services/bing_live.py`)
- [ ] Cliente HTTP con `httpx` contra
      `https://ssl.bing.com/webmaster/api.svc/json/<Método>?apikey=…`, 15 s de
      timeout, respuesta envuelta en `{"d": …}` y fechas `/Date(ms)/`.
      La clave nunca en logs ni en mensajes de error (se redacta de la URL).
- [ ] `connection_for(db, client)`: la fila de `client_bing_connections` con la
      clave descifrada y su `site_url`. Nada de buscar entre cuentas.
- [ ] `user_sites(api_key)`: `GetUserSites` (para conectar).
- [ ] `check(db, client)`:
      - URLs: watches activas (≤ 25) o la home.
      - `GetUrlInfo(site, url)` por URL, 4 a la vez, sin transacción abierta.
        Estado: `crawled` (HTTP 2xx y fecha de rastreo), `crawl_error` (rastreada
        con otro código), `discovered` (descubierta, sin rastreo), `unknown`
        (Bing no la conoce). Días desde el último rastreo.
      - `GetPageStats(site)` UNA vez: impresiones, clics y posición media por
        página en las últimas 4 semanas con datos (posición ponderada por
        impresiones, regla global 8). Se cruza con las URLs normalizando
        (`normalize_site_url`: barra final, sin query).
      - Devuelve `{site_url, checked_at, urls: [...], totals}`.
- [ ] `page_queries(db, client, url)`: `GetPageQueryStats(site, url)` → top 10
      consultas de esa URL (misma ventana y ponderación). Sólo al desplegar la fila.
- [ ] Errores `{"code","message"}` como `gsc_live`: 409 `not_connected`,
      409 `invalid_key` (y marca la conexión `invalid`), 409 `site_lost` (la
      cuenta ya no ve `site_url`), 429 `rate_limited` (cuota de Bing), 502
      `bing_error`.

### 3. API de la comprobación (mismo `api/routes/client_bing.py`)
- [ ] `POST /api/clients/{id}/bing/check` y
      `POST /api/clients/{id}/bing/page-queries` (`{url}`; la URL tiene que ser
      una de las que se comprueban). POST a propósito: gasta cuota de Bing y no
      debe dispararse solo al volver a la pestaña. Lectura de `clients`, mismo
      404 que `/{id}/status`, `bing_live_limiter` 10/min por persona.

### 4. Interfaz (`components/clients/seo-control/seo-bing-card.tsx`)
- [ ] En Control SEO, debajo de lo de Google. Sin conexión: "Conecta Bing en
      los ajustes del cliente" con enlace (`?tab=ajustes&foco=bing`) si es
      admin, o "Pide a un admin que conecte Bing" si no. Conexión `invalid`:
      "La clave de Bing ya no vale" con el mismo enlace. Con conexión: botón "Comprobar en
      Bing" (no automático), tabla URL · estado · último rastreo (hace N días) ·
      impresiones · posición media; fila desplegable con las consultas.
- [ ] Una frase arriba: "ChatGPT y Copilot parten de los resultados de Bing. Una
      URL que Bing no rastrea difícilmente aparece ahí." Sin prometer citas.
- [ ] Sin URLs vigiladas: aviso con enlace a la pestaña Web para añadirlas.
- [ ] `useMutation`, resultado en estado local (no caché persistente).

### 5. Privacidad y documentación
- [ ] `/privacidad` (`pages/public-legal.tsx`): The Agency lee de Bing Webmaster
      Tools, con la clave de cada web que pone un admin, el estado de rastreo y el
      rendimiento de las URLs al pulsar "Comprobar"; no guarda esas cifras.
- [ ] Sección "Bing (indexación y posición)" en `the-agency/CLAUDE.md`.

### 6. Tests
- [ ] `tests/test_bing_live.py` con `httpx.MockTransport` (como
      `test_web_health.py`) y fixture autouse que impida salir a la red:
      parseo de `/Date()`, clasificación, elección del sitio, ponderación de
      posición, clave redactada en errores, 401 → `invalid_key`.
- [ ] Integración: esquema de la migración (instalación limpia y subida) y
      rutas (permisos, 404, admin para conexiones, la clave nunca vuelve).
- [ ] Front: `seo-bing-card.test.tsx` y `client-bing-card.test.tsx`.
- [ ] Antes y después: `pytest`, `npm run test`, `npx tsc --noEmit`.

### 7. Verificación real
- [ ] Con la clave de UNA web, en local: conectarla y comprobar ese cliente
      (con URLs vigiladas) y contrastar 2-3 URLs con el inspector de URLs de
      Bing Webmaster Tools.

## Fase 2 (sólo si la fase 1 se usa; pedir aprobación)
- Job diario `bing` (lock 23) que guarde el último estado por URL y avise en la
  campana si una URL vigilada deja de estar rastreada o lleva > N días sin
  rastreo. Obliga a actualizar `/privacidad` (se guardarían cifras).
- Botón "Pedir indexación" (`SubmitUrlBatch` o IndexNow) con la cuota a la vista.
- Herramienta MCP `bing_status` (sólo lectura).
- Citas en Copilot (AI Performance) si Microsoft lo saca en la API.
