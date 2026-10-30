# The Agency MCP

Servidor MCP local para manejar The Agency desde Claude (Claude Code o Claude
Desktop): preguntar qué tienes hoy, buscar y crear tareas, cambiarlas de estado,
registrar tiempo, usar el temporizador, apuntar cosas en el inbox, escribir el
daily y ver cómo va un cliente.

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
| `list_dailys` | Tus dailys recientes, con su estado y si ya salieron en Discord |
| `client_overview` | Cómo va un cliente (por id o nombre): estado y motivos, tráfico, resumen, horas, tareas abiertas, lo que espera al cliente y el último resumen con su entrega |
| `list_suggestions` | Sugerencias y fallos del botón "Sugerencias o fallos" (pendientes, hechas o todas): texto, quién, cuándo, desde qué página y quién la cerró. Un admin ve las de todos; el resto, las suyas. Sólo lectura |
| `web_status` | Webs de un cliente: si responden (estado, % de 24 h y 30 días, caídas recientes) y cambios sin revisar por severidad con los últimos críticos/avisos y su enlace. Sin cliente: webs caídas o bloqueadas ahora y clientes con cambios críticos sin revisar |
| `gsc_properties` | Propiedades de Search Console de un cliente: la principal y las de su dominio que vea una cuenta conectada, con tipo, permiso y último día con datos. Sólo lectura |
| `gsc_query` | Search Console en vivo (`searchanalytics.query`) para cualquier periodo de los 16 meses: filas por fecha, consulta, página, país, dispositivo o aparición (tabla separada por tabuladores), con filtros, paginación y los totales de Google del mismo filtro (incluyen lo anonimizado). Sólo lectura |
| `ga4_properties` | Propiedad de GA4 de un cliente, qué cuenta conectada la ve y último día con datos; si nadie la ve, por qué (sin acceso, sin permiso de Analytics, reconectar). Sólo lectura |
| `ga4_query` | GA4 en vivo (`runReport` de la Data API) para cualquier periodo: sesiones, usuarios, eventos clave, páginas vistas y engagement por canal, landing, fuente/medio, campaña, dispositivo, país, ciudad o evento (tabla separada por tabuladores), con filtros AND, paginación (`offset`) y los totales que calcula GA4 para el mismo informe. Sólo lectura |
| `create_task` | Crea una tarea (si no dices a quién, te la asigna a ti) |
| `update_task` | Cambia estado, prioridad, fechas, responsable, espera… |
| `comment_task` | Comenta una tarea |
| `draft_task` | Pide a la IA un primer borrador del entregable siguiendo el procedimiento de la tarea (queda como comentario marcado; no se envía) |
| `capture_inbox` | Apunta una idea en el inbox |
| `log_time` | Registra tiempo a mano |
| `timer` | Temporizador: estado, arrancar, pausar, reanudar, parar |
| `submit_daily` | Guarda tu daily y lo estructura con IA (hasta 90 s). Queda en borrador |
| `send_daily_to_discord` | **Publica** uno de tus dailys en Discord. No se deshace con ⌘Z |

`client_overview` omite lo que tu usuario no puede leer (tareas, resúmenes,
horas, web) en vez de fallar. `web_status` necesita lectura del módulo Webs
(`web`); sin ella lo dice en vez de dar un 403. No enseña nada de Search Console
ni de GA4: para eso están `gsc_*` y `ga4_*`. `gsc_query`, `gsc_properties`,
`ga4_query` y `ga4_properties` necesitan lectura de clientes, son de sólo
lectura y preguntan a Google en el momento (nada se guarda ni se lee de lo
importado); los números salen sin redondear y el CTR y el `engagementRate` en
decimal (0.047). En `ga4_query`, `regex` casa con el valor entero. `send_daily_to_discord` sólo envía dailys propios,
también si eres admin, y manda la revisión leída: si alguien lo edita entre
medias, el backend lo rechaza.

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
| `AGENCY_TIMEOUT` | `30` | Segundos por llamada (el parseo del daily usa 90, como la web) |

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
2. Añádela en `agency_mcp/server.py` con `@mcp.tool(annotations=READ | WRITE | PUBLISH)`
   (`PUBLISH` para lo que sale fuera de The Agency, como Discord)
   y un docstring que diga cuándo usarla: es lo que lee el modelo.
3. Devuelve texto compacto (`agency_mcp/format.py`), no el JSON entero.
4. Test en `tests/test_server.py`: qué se manda y qué se devuelve.

No añadas herramientas de borrado sin hablarlo antes.
