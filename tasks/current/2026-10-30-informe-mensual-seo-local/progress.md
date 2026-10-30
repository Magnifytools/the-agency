# Progreso

- [x] 1. GA4 en vivo + MCP (subagente): 71 tests backend + 80 MCP en verde.
- [x] 2. Plantilla en el repo (`backend/report_templates/cigarral/`) + render + Dockerfile
      (chromium + fonts-liberation). Regenera octubre con el HTML idéntico al entregado.
- [x] 3. Migración `local_reports_v1` + modelos + test de esquema.
- [x] 4. Cálculo (`services/local_report/`): comprobado EN VIVO contra Search Console
      de producción (1-26 oct: 404/5.817, 306/319, 203/17, 1.230, grupos 29/15/7,
      tabla y páginas iguales; septiembre completo 356/6.562).
- [x] 5. IA (`ai.py`, en segundo plano) + reglas y guía junto a la plantilla. Probado
      con la API real: ~50 s, 29 textos, sin palabras prohibidas. La respuesta trae un
      bloque `thinking` antes del texto (arreglado).
- [x] 6. API `/api/clients/{id}/local-report` + tests de integración.
- [x] 7. Frontend: pestaña "Informe SEO local" (Resultados, con `gsc_url`). Probada en
      una base de previsualización (`the_agency_preview`): ver octubre importado, nueva
      versión, editar, generar con Chromium real, borrador con IA real, móvil.
- [x] 8. `scripts/import_local_report.py` (octubre como versión entregada).
- [x] 9. CLAUDE.md, /privacidad (+ test), README del MCP (subagente).

## Producción
1. HECHO 30 oct 2026: PR #222 mergeado (18500a6), desplegado con `local_reports_v1`.
2. HECHO: octubre importado (versión #2, entregada, comprobaciones OK, HTML idéntico
   al entregado, 5 fuentes). Configuración: plantilla cigarral, proyecto #18.
3. Cigarral no tiene propiedad de GA4: ponerla en Ajustes del cliente cuando haya acceso.

## Hecho después
- La entrega del informe SEO local cuenta como informe mensual (aviso, pendiente,
  cartera, dashboard y "Para entregar"). Cigarral con la política mensual encendida.
- `editorial.nota_final` no lo pinta la plantilla v6: se dejó fuera del editor y de la IA.
