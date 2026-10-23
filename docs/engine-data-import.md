# Importar de The Engine posiciones y leads (una sola vez)

> 22 oct 2026. The Engine se retira (ver
> `tasks/current/2026-10-21-web-y-control-seo/anvil-vs-engine.md`). Dos datos
> sólo existen allí y The Agency se los queda:
>
> - **Historial de posiciones** (`keyword_positions`): Sage desde el 4 dic 2024,
>   más de los 16 meses que guarda Google.
> - **Leads por landing** (`lead_attribution`, ~17k filas).
>
> Desde este PR The Agency importa los leads por su cuenta cada día
> (`services/ga4_leads.py`). Esto sólo trae lo que The Agency no puede pedir ya
> a Google. Hacerlo ANTES de congelar y borrar el Supabase de Engine (fase 1).

## 0. Antes de nada

1. Desplegado este PR (migración `20261022_leads_engine_v1`).
2. En The Agency, en los Ajustes de cada cliente:
   - **Google Search Console URL** puesta (posiciones). Sin ella el script se
     niega: la poda diaria borraría lo importado.
   - **GA4 Property ID** y **Eventos que cuentan como lead** (leads). En Engine
     eran `generate_lead_*` (uno por curso: `generate_lead_cpe`, `…_tsaf`…):
     para mantener las mismas cifras, poner `generate_lead_*`. El script sólo
     importa los eventos que la propiedad cuenta hoy.
3. Mejor si ya ha pasado una vez el job diario de Search Console (`gsc_detail`)
   y el de GA4 (`ga4`) con esa configuración: así The Agency sabe qué meses y
   días son suyos y el script sólo rellena lo anterior. Si no, el script importa
   todo y avisa; cuando The Agency importe después, **sus** meses/días
   sustituyen a los de Engine (Google manda).

## 1. Exportar de Engine (Supabase)

Con la cadena de conexión de Postgres del proyecto de Engine (Supabase →
Project Settings → Database → Connection string, modo *Session*), desde un
portátil con `psql`:

```bash
export ENGINE_DB_URL='postgresql://postgres.<ref>:<password>@aws-0-…pooler.supabase.com:5432/postgres'
```

Buscar el `project_id` de cada cliente:

```sql
SELECT id, name, domain, gsc_property, ga4_property FROM projects ORDER BY name;
```

**Posiciones** (una fila por keyword y día; Engine guardaba siempre `device = 'desktop'`):

```bash
psql "$ENGINE_DB_URL" -c "\copy (
  SELECT k.keyword, kp.date, kp.position, kp.clicks, kp.impressions, kp.url, kp.device
  FROM keyword_positions kp
  JOIN keywords k ON k.id = kp.keyword_id
  WHERE kp.project_id = <ID>
  ORDER BY kp.date, k.keyword
) TO 'engine_positions_<cliente>.csv' WITH (FORMAT csv, HEADER true)"
```

**Leads** (una fila por día, host, landing, evento y canal):

```bash
psql "$ENGINE_DB_URL" -c "\copy (
  SELECT date, landing_host, landing_page, event_name, channel, leads
  FROM lead_attribution
  WHERE project_id = <ID>
  ORDER BY date, landing_host, landing_page, event_name, channel
) TO 'engine_leads_<cliente>.csv' WITH (FORMAT csv, HEADER true)"
```

Alternativa sin `psql`: Supabase → SQL editor → la misma `SELECT` (sin el
`\copy (…) TO …`) → *Download CSV*. Ojo: el editor puede cortar resultados
grandes; comprobar que el número de filas del CSV coincide con un
`SELECT count(*)` de la misma consulta. Con `\copy` no hay corte.

Guardar los CSV fuera del repo y borrarlos al terminar (llevan datos de
clientes).

## 2. Importar en The Agency (primero simulacro)

Los scripts sólo necesitan `DATABASE_URL` (asyncpg) de la base destino. Con la
CLI de Railway, desde la raíz del repo y enlazado al proyecto de The Agency
(`railway link`):

```bash
# URL pública del Postgres de The Agency (desde el portátil no se llega a la interna):
railway run --service Postgres -- printenv DATABASE_PUBLIC_URL
export DATABASE_URL='postgresql+asyncpg://…'   # la de arriba, cambiando postgresql:// por postgresql+asyncpg://

# Posiciones (cliente de The Agency = su id en /clients/<id>)
railway run --service the-agency -- env DATABASE_URL="$DATABASE_URL" \
  backend/venv/bin/python -m backend.scripts.import_engine_positions \
  --csv ~/engine_positions_sage.csv --client-id <ID> --site-url 'sc-domain:…' --dry-run

# Leads (propiedad de GA4, sólo dígitos)
railway run --service the-agency -- env DATABASE_URL="$DATABASE_URL" \
  backend/venv/bin/python -m backend.scripts.import_engine_leads \
  --csv ~/engine_leads_fit.csv --property-id <PROPERTY_ID> --dry-run
```

(`railway run` sólo añade el resto de variables del servicio; el
`env DATABASE_URL=…` hace que se use la URL pública. Sin la CLI vale igual con
`export DATABASE_URL=…` y la misma orden de Python.)

El simulacro hace la importación entera en una transacción y la deshace: los
recuentos son los reales. Si sale bien, la misma orden sin `--dry-run`. Repetirla
da lo mismo (sustituye lo importado antes en esos meses/días).

### Qué hace cada script

`import_engine_positions` → `gsc_query_monthly` con `source = 'engine'`:

- Consulta normalizada como la devuelve Search Console (minúsculas, espacios
  colapsados): en Engine había keywords a mano en mayúsculas (`TSAF`).
- Por mes: clics e impresiones **sumados**; posición **ponderada por
  impresiones**. Descarta filas sin posición o sin consulta.
- Sólo meses **completos** del CSV y **anteriores al primer mes que The Agency
  ya tiene** de Google para esa web. Nunca pisa un mes propio.
- `--site-url` es una comprobación: tiene que ser la propiedad del cliente.
- Aborta si el cliente no está activo o no tiene propiedad.

`import_engine_leads` → `ga4_lead_daily`:

- Landing y canal normalizados igual que la importación diaria: host + ruta sin
  `utm_*`, `gclid`, `fbclid`…; el canal `unknown` de Engine pasa a `(not set)`.
  Filas antiguas de Engine sin host quedan sólo con la ruta.
- Sólo eventos que la propiedad cuenta hoy como lead; sólo días **anteriores al
  primero que importó The Agency** (`ga4_property_sync.leads_covered_from`) y
  dentro de la retención de 16 meses (lo anterior se borraría esa misma noche).
- Aborta si la propiedad no es de ningún cliente activo.

## 3. Comprobar

En The Agency (`railway connect Postgres` o cualquier cliente SQL):

```sql
-- Posiciones: qué hay de cada origen
SELECT source, min(month), max(month), count(*) AS filas, sum(clicks) AS clics
FROM gsc_query_monthly WHERE site_url = 'sc-domain:…'
GROUP BY source ORDER BY source;

-- Posiciones: mes a mes lo importado (para cotejar con Engine)
SELECT month, sum(clicks) AS clics, sum(impressions) AS impresiones,
       round((sum(weighted_position_sum) / nullif(sum(impressions), 0))::numeric, 2) AS posicion
FROM gsc_query_monthly WHERE site_url = 'sc-domain:…' AND source = 'engine'
GROUP BY month ORDER BY month;

-- Leads: lo importado frente a lo de The Agency
SELECT (date < s.leads_covered_from OR s.leads_covered_from IS NULL) AS de_engine,
       min(date), max(date), count(*) AS filas, sum(leads) AS leads
FROM ga4_lead_daily d LEFT JOIN ga4_property_sync s USING (property_id)
WHERE d.property_id = '<PROPERTY_ID>' GROUP BY 1;
```

En Engine, la misma cuenta mensual para cotejar:

```sql
SELECT date_trunc('month', kp.date)::date AS month, sum(kp.clicks) AS clics, sum(kp.impressions) AS impresiones,
       round((sum(kp.position * kp.impressions) / nullif(sum(kp.impressions), 0))::numeric, 2) AS posicion
FROM keyword_positions kp WHERE kp.project_id = <ID> AND kp.position > 0
GROUP BY 1 ORDER BY 1;

SELECT min(date), max(date), count(*), sum(leads) FROM lead_attribution WHERE project_id = <ID>;
```

(Las cifras de Engine por mes coinciden con lo importado salvo el mes
incompleto final, los meses que ya tenía The Agency y, en leads, los eventos
que no cuentan y los días fuera de la retención: el script imprime cada uno de
esos recuentos.)

En la app: Control SEO → una consulta → historial: los meses importados salen
antes de los de Google, con la nota "importado de The Engine".

## Qué hay que saber

- **Retención.** Lo importado de Engine en `gsc_query_monthly` NO caduca a los
  16 meses (la política de privacidad lo dice), pero se borra como lo demás si
  la web deja de tener cliente activo o si se purga la cuenta de Google al
  desconectarla. Los leads importados sí caducan a los 16 meses, como los
  propios.
- **Hueco con el tiempo.** Los meses propios de The Agency siguen caducando a
  los 16 meses. Hoy (oct 2026) Engine cubre dic 2024 → jun 2025 y The Agency
  jul 2025 en adelante; en noviembre caduca jul 2025 y se abre un hueco que
  crece un mes cada mes. Si se quiere el historial seguido, repetir el import
  con el mismo CSV (rellena los meses que The Agency ya no tiene, porque son
  anteriores a su primer mes) antes de borrar el CSV, o decidir guardar
  también como `engine` esos meses. No está automatizado a propósito.
- **Calidad de los datos de Engine.** Engine pedía (consulta, día, página) y se
  quedaba con UNA página por consulta y día; además con un tope de 25.000 filas
  por petición. Las posiciones sirven para ver la evolución, pero los clics e
  impresiones de consultas con varias URLs pueden quedarse cortos frente a
  Search Console. Por eso nunca sustituyen a un mes de Google.
- Nada de esto va a la IA (lo vigila `test_el_detalle_de_search_console_no_llega_a_la_ia`).
