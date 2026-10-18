# The Agency MCP

Servidor MCP local para manejar The Agency desde Claude (Claude Code o Claude
Desktop): preguntar qué tienes hoy, buscar y crear tareas, cambiarlas de estado,
registrar tiempo, usar el temporizador y apuntar cosas en el inbox.

Es un cliente más de la API, como la extensión de Chrome. Entra con **tu
usuario**, así que ves y cambias lo mismo que en la web, con tus permisos, y
todo lo que cambia queda en tu historial de Deshacer (⌘Z en la web).

No tiene herramientas de borrado. Lo destructivo se hace en la web.

## Herramientas

| Herramienta | Qué hace |
|---|---|
| `today_agenda` | Agenda del día: planificadas, arrastradas, completadas, temporizador e inbox |
| `list_tasks` | Busca tareas con filtros (por defecto, las tuyas abiertas) |
| `get_task` | Detalle de una tarea con checklist y comentarios |
| `search` | Búsqueda global por nombre (clientes, proyectos, tareas) |
| `list_projects` | Proyectos de la cartera o cerrados |
| `list_team` | Personas del equipo con su id |
| `list_time_entries` | Horas de un rango, con total por cliente |
| `list_inbox` | Notas del inbox por procesar |
| `create_task` | Crea una tarea (si no dices a quién, te la asigna a ti) |
| `update_task` | Cambia estado, prioridad, fechas, responsable, espera… |
| `comment_task` | Comenta una tarea |
| `capture_inbox` | Apunta una idea en el inbox |
| `log_time` | Registra tiempo a mano |
| `timer` | Temporizador: estado, arrancar, pausar, reanudar, parar |

## Instalación

Necesita Python 3.11 o superior (en este Mac, `/opt/homebrew/bin/python3.12`).

```bash
cd "/Users/david/Public/Código/the-agency/mcp-server" && /opt/homebrew/bin/python3.12 -m venv .venv && .venv/bin/pip install -e .
```

Guarda la contraseña en el Llavero de macOS, así no queda en texto plano en
ninguna configuración (te la pedirá al ejecutarlo):

```bash
security add-generic-password -s the-agency-mcp -a david@magnify.ing -w
```

### Claude Code

```bash
claude mcp add the-agency --scope user -e AGENCY_EMAIL=david@magnify.ing -- "/Users/david/Public/Código/the-agency/mcp-server/.venv/bin/agency-mcp"
```

### Claude Desktop

En `~/Library/Application Support/Claude/claude_desktop_config.json`, dentro de
`mcpServers`:

```json
"the-agency": {
  "command": "/Users/david/Public/Código/the-agency/mcp-server/.venv/bin/agency-mcp",
  "env": { "AGENCY_EMAIL": "david@magnify.ing" }
}
```

Reinicia Claude Desktop después de guardarlo.

## Variables de entorno

| Variable | Por defecto | Para qué |
|---|---|---|
| `AGENCY_EMAIL` | (obligatoria) | Tu usuario de The Agency |
| `AGENCY_PASSWORD` | Llavero | Contraseña. Si no está, se lee del Llavero (servicio `the-agency-mcp`) |
| `AGENCY_URL` | `https://agency.magnifytools.com` | `http://localhost:8004` para desarrollo |
| `AGENCY_TIMEZONE` | `Europe/Madrid` | Para saber qué es "hoy" |
| `AGENCY_TIMEOUT` | `30` | Segundos por llamada |

## Cómo funciona la sesión

Entra una vez con `/api/auth/login` y manda el token como `Bearer`. El token
dura 8 h; ante un 401 vuelve a entrar una sola vez y repite la llamada. Las
cookies del login se descartan: con cookie y sin Bearer el backend exigiría
CSRF.

El backend limita el login a 5 intentos cada 5 minutos por email e IP. El
servidor entra una vez por proceso, así que en uso normal no se nota.

## Tests

```bash
cd "/Users/david/Public/Código/the-agency/mcp-server" && .venv/bin/pip install -e ".[dev]" && .venv/bin/python -m pytest -q
```

Los tests usan un backend falso (`httpx.MockTransport`) y el cliente MCP en
memoria: no hacen falta red ni base de datos.

## Añadir una herramienta

1. Mira el endpoint y su esquema en `backend/api/routes/` y `backend/schemas/`.
2. Añádela en `agency_mcp/server.py` con `@mcp.tool(annotations=READ | WRITE)`
   y un docstring que diga cuándo usarla: es lo que lee el modelo.
3. Devuelve texto compacto (`agency_mcp/format.py`), no el JSON entero.
4. Test en `tests/test_server.py`: qué se manda y qué se devuelve.

No añadas herramientas de borrado sin hablarlo antes.
