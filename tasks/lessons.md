#### 2026-09-22 The Agency — Contrato de creación del timer
- Error: la regresión asumió 200 al iniciar el timer, pero la ruta crea el recurso y responde 201.
- Regla: al extender una prueba de flujo, comprobar el código de estado y el cuerpo requerido por cada ruta antes de fijar la llamada.
- Impacto: dos fallos locales de la prueba focal; no afectaron a datos ni producción.
