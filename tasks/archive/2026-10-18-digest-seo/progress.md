# Progreso

Hecho (18 oct 2026), rama `feat/digest-seo`:
- Migración `20261018_gsc_v1` (3 tablas) aplicada en BD nueva y en BD existente.
- `gsc_service` (OAuth, sitios, consulta diaria, sync, resumen mensual),
  rutas `/api/gsc/*`, job diario `gsc`.
- Collector añade `seo` sólo en meses naturales; bloque pintado por código en
  los 4 formatos; `include_seo` en el contenido.
- Frontend: Ajustes → Search Console, ficha del cliente (sugerencias +
  estado), panel en el editor del resumen con enlace a informes de The Engine.
- Arreglo de paso: el prompt ya no dice "esta semana" en resúmenes mensuales.
- Tests: 21 unit + 9 integración nuevos; suites completas en verde (653 unit,
  839 integración, 580 frontend). Verificado en navegador con datos locales.

Pendiente fuera del código (producción):
- Google Cloud: activar Search Console API, redirect `/api/gsc/callback`,
  scope `webmasters.readonly`.
- Conectar la cuenta en Ajustes y rellenar `gsc_url` de cada cliente.
- No probado contra la API real de Google (sólo con datos locales y dobles).
