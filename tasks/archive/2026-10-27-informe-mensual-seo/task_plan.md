# Plan — Informe mensual con el detalle de Search Console (27 oct 2026)

Pedido por David tras la revisión del vídeo de Ruk Lab (min. 48): el resumen
mensual pasa de 4 totales a un informe de verdad. Pintado con código, nunca por la IA.

## Qué entra
1. **Interanual completo**: clics, impresiones, CTR y posición frente al mismo
   mes del año anterior (hoy sólo clics). GA4: visitas y conversiones. Ya está
   en `raw_context` (`vs_year_ago`): sólo falta pintarlo.
2. **Top 5 consultas** y **top 5 páginas** del mes por clics, con su cambio
   frente al mes anterior.
3. **Oportunidades**: hasta 5 consultas sin marca en posición media 8–20 con
   ≥ 30 impresiones en el mes, por impresiones.
4. **Marca / sin marca / sin clasificar** (clics), si el cliente tiene `brand_terms`.

## Diseño
- **Foto del mes** en tabla propia `digest_seo_details` (PK `digest_id`, en
  cascada con el resumen; `site_url`, `payload` JSONB, `computed_at`). Migración
  `digest_seo_detail_v1`. No va en `raw_context`: `raw_context` llega entero al
  generador (también al regenerar por tono) y el detalle no puede acercarse a la IA.
- **Cuándo se calcula**: al pintar (vista previa, PDF, editor) mientras la versión
  NO ha salido de la app → se recalcula y se guarda si cambia. Cuando ya salió,
  se lee la guardada (lo que se envió no cambia; un resumen entregado antes de
  esto no gana el bloque a posteriori). La página pública y su PDF sólo leen.
- **Ventana**: el mes natural del resumen y el mes anterior, desde
  `gsc_query_daily`/`gsc_page_daily`. Sin detalle completo del mes → sin bloque.
  Sin el mes anterior entero → sin columna de cambio.
- **Retención y purga** como el detalle: `gsc_detail_service.prune` borra las de
  webs sin cliente activo; desconectar con `purge_data` también.
- **IA**: `digest_seo_detail`/`DigestSeoDetail` a `_FORBIDDEN` de
  `test_gsc_detail.py`. `client_share_links.py` sale de `_ai_paths` (no llama a
  la IA; la política ya permite el bloque de cifras en el enlace del cliente).
- **Política** (`public-legal.tsx`) y CLAUDE.md en el mismo PR.

## Pasos
1. Migración + modelo.
2. `seo_control`: agregados sin caché para un rango arbitrario.
3. `services/digest_seo_detail.py` (cálculo puro + carga/guardado).
4. `digest_seo`: interanual completo y bloques nuevos (texto y HTML); `digest_ga4`
   interanual; PDF.
5. Rutas: render, PDF, GET /{id} (para el editor), enlace público y su PDF.
6. Frontend: `DigestSeoPanel` con las listas y el interanual; tipos.
7. Tests (unidad + integración con Postgres) y verificación en navegador.
