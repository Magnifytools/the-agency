# Informe mensual SEO local (Cigarral de Caravantes, cliente #28)

Encargo: `PROMPT_para_The_Agency.md` del ZIP `Informe_mensual_para_The_Agency.zip`
(30 oct 2026). Rama `feat/informe-mensual-seo-local`.

## Decisiones

- **Plantilla en el repo**, sin tocar su diseño: `backend/report_templates/seo_local/`
  (`informe.html.j2`, `estilos.css`, `generar.py` adaptado para importarse) y el
  logo y el plan por cliente en la configuración (BD).
- **Chromium en la imagen** (Debian `chromium` + `playwright` de pip): lo pide el
  encargo (generar.py en el servidor). Se renderiza HTML propio con la red
  cortada (`page.route` aborta todo): no reabre la SSRF que motivó "sin
  Playwright" en Webs.
- **Entidad propia** `client_local_reports` (versiones por periodo, se
  sobrescribe hasta que se entrega, como los resúmenes) en vez de colgarlo de
  `weekly_digests`: el contenido no tiene nada que ver con un resumen y el
  editor/IA/renderers de resúmenes no lo entenderían. Entrega confirmada en la
  propia versión. Integración con `report_unsent`/"Para entregar": pendiente,
  se anota como siguiente paso.
- **Datos de Google en vivo** (`gsc_live`, `ga4_live`), nunca lo guardado: así
  la guardia de privacidad sigue valiendo y los informes de meses pasados se
  rehacen con lo guardado en la versión (`datos.json`).
- **IA**: redacta `editorial` + los 29 `textos` (+ `informe.modo/nota` y el
  motivo de las tareas en espera). Se guarda como borrador editable. La
  política de privacidad se actualiza: cifras agregadas de Search Console y GA4
  del informe sí llegan a la IA.

## Pasos

1. GA4 en vivo: `services/ga4_live.py`, `POST /api/clients/{id}/ga4/query`,
   `GET .../ga4/properties`, MCP `ga4_query`/`ga4_properties` + tests (subagente).
2. Plantilla en el repo + `render()` reutilizable + dependencias (jinja2 ya,
   playwright) + Dockerfile (chromium y fuentes).
3. Migración `local_report_v1`: `client_local_report_configs`,
   `client_local_reports`, `client_local_report_sources`.
4. Cálculo (`services/local_report/`): periodos, Search Console, páginas, GA4,
   plan desde tareas, ficha de Google (CSV), rastreo (CSV).
5. IA: borrador de textos con reglas de CONTINUIDAD y tono de octubre.
6. API: config, crear versión/recalcular, subir fuentes, editar textos,
   redactar con IA, generar, descargar HTML/PDF, entregar.
7. Frontend: pestaña "Informe SEO local" en Resultados de la ficha.
8. Pruebas de aceptación con `referencia_octubre_2026/` (cifras, 29 textos,
   11 secciones, 8 iconos, PDF incrustado = suelto, palabras prohibidas).
9. Documentación (CLAUDE.md, /privacidad) y PR.
