# Servidor MCP para The Agency

Objetivo: manejar The Agency desde Claude (Code / Desktop) con herramientas
estructuradas: consultar el día, tareas, proyectos, horas e inbox, y crear o
cambiar tareas, notas, tiempo y temporizador.

## Diseño

- **Servidor local por stdio**, en `mcp-server/`. Es un cliente más de la API
  REST, como la extensión de Chrome. Cero cambios en el backend.
- **Auth**: el usuario de la persona (email + contraseña en variables de
  entorno). Login a `/api/auth/login`, Bearer en cada llamada, re-login
  automático ante un 401 (el JWT caduca a las 8 h). Bearer no pasa por CSRF.
- Como cada llamada va con el usuario real, los permisos por módulo se aplican
  solos y los cambios entran en su historial de Deshacer (⌘Z).
- **Sin herramientas de borrado.** Lo destructivo se hace en la web.
- Python 3.12 (`mcp` exige >= 3.10), venv propio en `mcp-server/.venv`.

## Herramientas v1

Lectura: `today`, `list_tasks`, `get_task`, `search`, `list_projects`,
`list_time_entries`, `list_inbox`.
Escritura: `create_task`, `update_task`, `comment_task`, `capture_inbox`,
`log_time`, `timer`.

Fuera de v1: dailys (tienen flujo propio de hechos + revisión en la web).

## Pasos

1. Paquete `mcp-server/` con cliente HTTP (login, re-login, errores legibles).
2. Herramientas con salida compacta (no volcar JSON entero de TaskResponse).
3. Tests con `httpx.MockTransport` (sin red ni BD).
4. E2E local: Postgres 16 Homebrew + backend :8004 + seed + cliente MCP real
   por stdio llamando a las herramientas.
5. README con instalación en Claude Code y Claude Desktop.
