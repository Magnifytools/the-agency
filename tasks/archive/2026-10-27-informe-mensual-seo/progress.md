# Progress — Informe mensual con el detalle de Search Console

- 2026-10-27: hecho en `feat/informe-mensual-seo` (worktree
  `.claude/worktrees/informe-mensual`, desde `origin/main` d69a142). Sin commit.
  - Migración `digest_seo_detail_v1` + `DigestSeoDetail`; `services/digest_seo_detail.py`;
    `seo_control.range_aggregates/range_totals` (sin caché); retención en
    `gsc_detail_service.prune` y purga al desconectar (`routes/gsc.py`).
  - Pintado: `digest_seo` (texto/HTML, interanual completo), `digest_ga4`
    (interanual), `digest_pdf` (tablas; la fuente va al final del bloque).
  - Rutas: GET del resumen (editor), render, PDF, enlace público y su PDF.
  - Front: `DigestSeoPanel` con interanual y foto del mes; tipos.
  - Política (`public-legal.tsx`, ES y EN) y CLAUDE.md.
  - Tests: `test_digest_seo_detail.py` (14), integración (6 + 2 de esquema),
    guardia de la IA ampliada; panel (5). Front: 784 en verde.
  - Verificado en navegador con datos de PRUEBA (base aislada
    `the_agency_dev_informe`, cliente ficticio "Atleta Studio"): editor, vista
    previa del email y PDF de dos páginas. No hay datos reales de Search
    Console en ninguna base local.
- 2026-10-27: commit y PR pedidos por David.
