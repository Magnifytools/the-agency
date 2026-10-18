# Hallazgos

- La API ya servía para un cliente externo: el login devuelve el token en el
  cuerpo (para la extensión) y con Bearer no se exige CSRF. No hizo falta tocar
  el backend.
- El login deja cookies. Si se reenvían sin Bearer, el CSRF rechaza escrituras,
  así que el cliente las descarta.
- Login limitado a 5 intentos / 5 min por email+IP: dos e2e seguidos lo
  agotaron. El MCP entra una vez por proceso (token de 8 h), no afecta al uso.
- `POST /api/tasks` acepta `assign_to_current_user` (no se persiste) para
  asignarse una tarea sin saber el propio id.
- El arranque del backend exige `python -m backend.scripts.migrate` antes que
  el seed; `create_all` sólo no basta (falta `agency_schema_versions`).
- MCP SDK 2.x: `FastMCP` -> `MCPServer`; `ToolError` para fallos previstos.
- Los cambios hechos por MCP salen en `/api/changes/recent` del usuario:
  Deshacer funciona igual que desde la web.
