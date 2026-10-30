# Daily de Nacho: 502 al estructurar (daily_id=129)

Causa (logs Railway): notas vacías (solo hechos) -> Claude antepone prosa inventada al bloque ```json -> parse_claude_json falla -> 502 + doble toast.

1. ai_utils.parse_claude_json: extraer el objeto JSON aunque venga precedido de texto.
2. daily_parser: con notas vacías, decirlo explícitamente y no aceptar aportes libres (sin fact_keys).
3. api.ts: no duplicar "Error del servidor" en /dailys/{id}/reparse (la página ya muestra el detalle).
4. Tests + verificación con el caso real.
