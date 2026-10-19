"""Herramientas MCP de The Agency.

Cada herramienta es una llamada (o unas pocas) a la API REST con el usuario de
la persona. No hay herramientas de borrado: lo destructivo se hace en la web.
Todo lo que se cambia desde aquí entra en el historial de Deshacer (⌘Z).
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from datetime import date, datetime, timedelta
from typing import Annotated, Any, Literal
from zoneinfo import ZoneInfo

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from agency_mcp import format as fmt
from agency_mcp.client import AgencyClient, AgencyError

DEFAULT_URL = "https://agency.magnifytools.com"
KEYCHAIN_SERVICE = "the-agency-mcp"

TaskStatus = Literal["backlog", "pending", "in_progress", "waiting", "in_review", "advanced", "completed"]
Priority = Literal["urgent", "high", "medium", "low"]
ClearableField = Literal[
    "description", "due_date", "scheduled_date", "assigned_to", "project_id", "client_id",
    "estimated_minutes", "waiting_for", "follow_up_date", "link_url",
]
ACTIVE_STATUSES = "backlog,pending,in_progress,waiting,in_review,advanced"

READ = ToolAnnotations(readOnlyHint=True, openWorldHint=False)
WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False)
# Publica fuera de The Agency (Discord): no se puede deshacer con ⌘Z.
PUBLISH = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True)
# Lo mismo que da la web a las llamadas de dailys que esperan a Claude.
DAILY_AI_TIMEOUT = 90.0

INSTRUCTIONS = """\
The Agency es la herramienta interna de gestión de la agencia (Magnify): clientes,
proyectos, tareas, tiempo e inbox. Actúas con el usuario de la persona y con sus
permisos. Para actuar sobre algo necesitas su id: búscalo antes con `search`,
`list_tasks` o `list_projects`. Fechas en formato AAAA-MM-DD, zona Europe/Madrid.
Todo cambio se puede deshacer desde la web (⌘Z); no hay herramientas de borrado.
"""

DateStr = Annotated[str, Field(pattern=r"^\d{4}-\d{2}-\d{2}$", description="Fecha AAAA-MM-DD")]


def _opt_date(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise ToolError(f"Fecha no válida: {value!r}. Usa AAAA-MM-DD.") from exc


def build_server(client: AgencyClient, *, timezone: str = "Europe/Madrid") -> MCPServer:
    tz = ZoneInfo(timezone)
    mcp = MCPServer("the-agency", title="The Agency", instructions=INSTRUCTIONS)

    def today() -> date:
        return datetime.now(tz).date()

    async def call(coro) -> Any:
        try:
            return await coro
        except AgencyError as exc:
            raise ToolError(str(exc)) from exc

    # ── Lectura ──────────────────────────────────────────────────────────

    @mcp.tool(annotations=READ)
    async def today_agenda(
        day: Annotated[str | None, Field(description="Día AAAA-MM-DD. Por defecto, hoy.")] = None,
    ) -> str:
        """Agenda de un día de la persona: tareas planificadas, arrastradas de días
        anteriores, seguimientos con clientes que ya tocan y completadas, más el temporizador activo y las notas del inbox
        sin procesar. Es el mejor punto de partida para "¿qué tengo hoy?"."""
        d = _opt_date(day) or today().isoformat()
        sections = {}
        for section in ("planned", "carryover", "followups", "completed"):
            page = await call(client.get(
                "/api/tasks/agenda", date=d, section=section, assigned_to="me", page_size=50
            ))
            sections[section] = page
        timer = await call(client.get("/api/timer/active"))
        inbox = await call(client.get("/api/inbox/count"))

        out = [f"Agenda del {d}"]
        for section, title in (
            ("planned", "Planificadas para el día"),
            ("carryover", "Arrastradas (vencidas o de días anteriores)"),
            ("followups", "Seguimientos que ya tocan (esperando al cliente)"),
            ("completed", "Completadas ese día"),
        ):
            page = sections[section]
            out += ["", f"{title} ({page['total']}):",
                    fmt.task_list(page["items"], total=page["total"], empty="(ninguna)")]
        out += ["", fmt.timer_line(timer, tz), f"Inbox: {inbox.get('count', 0)} notas por procesar."]
        return "\n".join(out)

    @mcp.tool(annotations=READ)
    async def list_tasks(
        search: Annotated[str | None, Field(description="Texto a buscar en título o descripción")] = None,
        status: Annotated[list[TaskStatus] | None, Field(description="Estados. Por defecto, todos menos completed.")] = None,
        project_id: int | None = None,
        client_id: int | None = None,
        assigned_to: Annotated[str, Field(description="'me', 'all', 'unassigned' o el id de un usuario")] = "me",
        overdue: Annotated[bool | None, Field(description="Sólo tareas vencidas")] = None,
        due_from: DateStr | None = None,
        due_to: DateStr | None = None,
        limit: Annotated[int, Field(ge=1, le=200)] = 30,
    ) -> str:
        """Busca tareas con filtros. Por defecto, las tareas abiertas asignadas a la persona."""
        page = await call(client.get(
            "/api/tasks",
            search=search,
            status=",".join(status) if status else ACTIVE_STATUSES,
            project_id=project_id,
            client_id=client_id,
            assigned_to=None if assigned_to == "all" else assigned_to,
            overdue=overdue,
            due_date_from=_opt_date(due_from),
            due_date_to=_opt_date(due_to),
            page_size=limit,
        ))
        return fmt.task_list(page["items"], total=page["total"], empty="No hay tareas con esos filtros.")

    @mcp.tool(annotations=READ)
    async def get_task(task_id: int) -> str:
        """Detalle de una tarea: datos, descripción, checklist y comentarios."""
        task = await call(client.get(f"/api/tasks/{task_id}"))
        checklist = await call(client.get(f"/api/tasks/{task_id}/checklist"))
        comments = await call(client.get(f"/api/tasks/{task_id}/comments"))
        return fmt.task_detail(task, checklist or [], comments or [])

    @mcp.tool(annotations=READ)
    async def search(query: Annotated[str, Field(min_length=2)]) -> str:
        """Búsqueda global por nombre en clientes, proyectos y tareas (como ⌘K en la web).
        Úsala para encontrar ids a partir de un nombre."""
        results = await call(client.get("/api/search", q=query))
        out = []
        if results.get("clients"):
            out.append("Clientes:")
            out += [f"- #{c['id']} {c['name']}" + (f" ({c['company']})" if c.get("company") else "")
                    + f" · {c.get('status')}" for c in results["clients"]]
        if results.get("projects"):
            out.append("Proyectos:")
            out += [f"- #{p['id']} {p['name']}" + (f" · {p['client_name']}" if p.get("client_name") else "")
                    + f" · {fmt.PROJECT_STATUS.get(p.get('status'), p.get('status'))}"
                    for p in results["projects"]]
        if results.get("tasks"):
            out.append("Tareas:")
            out += [f"- #{t['id']} {t['title']}"
                    + (f" · {t['client_name']}" if t.get("client_name") else "")
                    + f" · {fmt.TASK_STATUS.get(t.get('status'), t.get('status'))}"
                    for t in results["tasks"]]
        return "\n".join(out) or f"Nada encontrado para {query!r}."

    @mcp.tool(annotations=READ)
    async def list_projects(
        client_id: int | None = None,
        archived: Annotated[bool, Field(description="True para ver los proyectos cerrados")] = False,
        limit: Annotated[int, Field(ge=1, le=200)] = 100,
    ) -> str:
        """Proyectos de la cartera (activos, en planificación o en pausa) o, con archived, los cerrados."""
        page = await call(client.get(
            "/api/projects",
            client_id=client_id,
            lifecycle="archive" if archived else "portfolio",
            page_size=limit,
        ))
        if not page["items"]:
            return "No hay proyectos."
        return "\n".join(f"- {fmt.project_line(p)}" for p in page["items"])

    @mcp.tool(annotations=READ)
    async def list_team() -> str:
        """Personas del equipo con su id, para asignar tareas o filtrar por persona."""
        page = await call(client.get("/api/users", page_size=100))
        users = [u for u in page["items"] if u.get("is_active", True)]
        return "\n".join(f"- #{u['id']} {u['full_name']} ({u['email']}) · {u['role']}" for u in users)

    @mcp.tool(annotations=READ)
    async def list_time_entries(
        date_from: DateStr | None = None,
        date_to: DateStr | None = None,
        user_id: Annotated[int | None, Field(description="Sólo admin: horas de otra persona")] = None,
    ) -> str:
        """Horas registradas en un rango (por defecto, la semana en curso), con el total
        por cliente y el detalle por entrada."""
        start = date.fromisoformat(_opt_date(date_from)) if date_from else today() - timedelta(days=today().weekday())
        end = date.fromisoformat(_opt_date(date_to)) if date_to else today()
        entries = await call(client.get(
            "/api/time-entries",
            date_from=f"{start.isoformat()}T00:00:00",
            date_to=f"{end.isoformat()}T23:59:59",
            user_id=user_id,
        ))
        if not entries:
            return f"Sin horas registradas entre {start} y {end}."
        total = sum(e.get("minutes") or 0 for e in entries)
        by_client: dict[str, int] = {}
        for e in entries:
            key = e.get("client_name") or "Sin cliente"
            by_client[key] = by_client.get(key, 0) + (e.get("minutes") or 0)
        out = [f"{fmt.hours(total)} entre {start} y {end}.", "", "Por cliente:"]
        out += [f"- {name}: {fmt.hours(m)}" for name, m in sorted(by_client.items(), key=lambda kv: -kv[1])]
        out += ["", "Entradas:"]
        for e in sorted(entries, key=lambda e: e.get("date") or ""):
            what = f"#{e['task_id']} {e.get('task_title')}" if e.get("task_id") else "sin tarea"
            note = f" — {e['notes']}" if e.get("notes") else ""
            out.append(f"- {fmt.day(e.get('date'))} {fmt.hours(e.get('minutes'))} · {what}{note}")
        return "\n".join(out)

    @mcp.tool(annotations=READ)
    async def list_inbox(
        include_processed: Annotated[bool, Field(description="Incluir notas ya convertidas o descartadas")] = False,
        limit: Annotated[int, Field(ge=1, le=100)] = 50,
    ) -> str:
        """Notas del inbox de la persona. Por defecto, sólo las que faltan por procesar."""
        notes = await call(client.get(
            "/api/inbox",
            status=None if include_processed else "pending,classified",
            limit=limit,
        ))
        if not notes:
            return "El inbox está vacío."
        return "\n".join(f"- {fmt.inbox_line(n)}" for n in notes)

    @mcp.tool(annotations=READ)
    async def list_dailys(
        limit: Annotated[int, Field(ge=1, le=50)] = 7,
        date_from: DateStr | None = None,
        date_to: DateStr | None = None,
    ) -> str:
        """Dailys (cierres del día) recientes de la persona, del más nuevo al más viejo:
        una línea por daily con su id, estado y si ya salió en Discord."""
        me = await call(client.get("/api/auth/me"))
        # Un admin vería los de todo el equipo: aquí sólo los suyos.
        dailys = await call(client.get(
            "/api/dailys", user_id=me["id"], limit=limit,
            date_from=_opt_date(date_from), date_to=_opt_date(date_to),
        ))
        if not dailys:
            return "No hay dailys en ese rango."
        return "\n".join(f"- {fmt.daily_line(d)}" for d in dailys)

    async def _resolve_client(client_id: int | None, name: str | None) -> int:
        if client_id is not None:
            return client_id
        if not name or len(name.strip()) < 2:
            raise ToolError("Indica client_id o el nombre del cliente (mínimo 2 letras).")
        found = (await call(client.get("/api/search", q=name.strip()))).get("clients") or []
        if not found:
            raise ToolError(f"No encuentro ningún cliente que se llame {name!r} (o no tienes acceso a clientes).")
        exact = [c for c in found if c["name"].casefold() == name.strip().casefold()]
        if len(exact) == 1 or len(found) == 1:
            return (exact or found)[0]["id"]
        options = "; ".join(f"#{c['id']} {c['name']}" for c in found)
        raise ToolError(f"Hay varios clientes para {name!r}: {options}. Repite con client_id.")

    async def _optional(coro) -> Any:
        """Partes del resumen que dependen de otro módulo: sin permiso se omiten."""
        try:
            return await coro
        except AgencyError as exc:
            if exc.status == 403:
                return None
            raise ToolError(str(exc)) from exc

    @mcp.tool(annotations=READ)
    async def client_overview(
        client_id: int | None = None,
        name: Annotated[str | None, Field(description="Nombre del cliente si no sabes su id")] = None,
    ) -> str:
        """Cómo va un cliente de un vistazo: estado (Actuar/Vigilar/Bien) con sus motivos,
        tráfico de Google, resumen periódico, horas del mes, tareas abiertas, lo que
        está esperando al cliente con su fecha de seguimiento y el último resumen
        (si se confirmó su entrega al cliente)."""
        cid = await _resolve_client(client_id, name)
        status = await call(client.get(f"/api/clients/{cid}/status"))
        common = {"client_id": cid, "is_recurring": False, "page_size": 30}
        open_page = await _optional(client.get(
            "/api/tasks", status=ACTIVE_STATUSES.replace("waiting,", ""), **common))
        waiting_page = await _optional(client.get("/api/tasks", status="waiting", **common))
        digests = await _optional(client.get("/api/digests", client_id=cid, limit=1))

        out = [f"Cliente #{cid} {status.get('client_name')}", *fmt.client_status_block(status)]
        if open_page is None:
            out += ["", "Tareas: sin permiso para verlas."]
        else:
            out += ["", f"Tareas abiertas ({open_page['total']}):",
                    fmt.task_list(open_page["items"], total=open_page["total"], empty="(ninguna)")]
            out += ["", f"Esperando al cliente ({waiting_page['total']}):",
                    fmt.task_list(waiting_page["items"], total=waiting_page["total"], empty="(nada)")]
        if digests:
            d = digests[0]
            line = (f"Último resumen: #{d['id']} {d['period_start']} → {d['period_end']} · "
                    f"{fmt.DIGEST_STATUS.get(d.get('status'), d.get('status'))}")
            events = await _optional(client.get(f"/api/digests/{d['id']}/external-delivery-events"))
            delivery = (events or {}).get("external_delivery") or {}
            if delivery.get("state") == "confirmed":
                line += f" · entregado al cliente el {fmt.day(delivery.get('confirmed_at'))}"
                if delivery.get("actor_name"):
                    line += f" por {delivery['actor_name']}"
            elif events is not None:
                line += " · entrega al cliente sin confirmar"
            if (events or {}).get("has_newer_version"):
                line += " (hay una versión más nueva del mismo periodo)"
            out += ["", line]
        elif digests is not None:
            out += ["", "Último resumen: ninguno."]
        return "\n".join(out)

    # ── Escritura ────────────────────────────────────────────────────────

    @mcp.tool(annotations=WRITE)
    async def create_task(
        title: Annotated[str, Field(min_length=1, max_length=255)],
        description: str | None = None,
        project_id: int | None = None,
        client_id: int | None = None,
        assigned_to: Annotated[int | None, Field(description="Id de usuario. Si se omite, se asigna a la persona.")] = None,
        priority: Priority = "medium",
        status: TaskStatus = "pending",
        due_date: DateStr | None = None,
        scheduled_date: Annotated[str | None, Field(description="Día AAAA-MM-DD en que se piensa hacer (aparece en su agenda)")] = None,
        estimated_minutes: Annotated[int | None, Field(ge=0)] = None,
        link_url: str | None = None,
    ) -> str:
        """Crea una tarea. Busca antes el id del proyecto o cliente si la persona lo nombra."""
        body: dict[str, Any] = {
            "title": title,
            "description": description,
            "project_id": project_id,
            "client_id": client_id,
            "priority": priority,
            "status": status,
            "estimated_minutes": estimated_minutes,
            "scheduled_date": _opt_date(scheduled_date),
            "link_url": link_url,
        }
        if due_date:
            body["due_date"] = f"{_opt_date(due_date)}T00:00:00"
        if assigned_to is None:
            body["assign_to_current_user"] = True
        else:
            body["assigned_to"] = assigned_to
        task = await call(client.post("/api/tasks", {k: v for k, v in body.items() if v is not None}))
        return f"Tarea creada: {fmt.task_line(task)}"

    @mcp.tool(annotations=WRITE)
    async def update_task(
        task_id: int,
        title: str | None = None,
        description: str | None = None,
        status: TaskStatus | None = None,
        priority: Priority | None = None,
        due_date: DateStr | None = None,
        scheduled_date: DateStr | None = None,
        assigned_to: int | None = None,
        project_id: int | None = None,
        client_id: int | None = None,
        estimated_minutes: Annotated[int | None, Field(ge=0)] = None,
        waiting_for: Annotated[str | None, Field(description="A quién o qué se espera (con status 'waiting')")] = None,
        follow_up_date: DateStr | None = None,
        link_url: str | None = None,
        clear: Annotated[list[ClearableField] | None, Field(description="Campos a vaciar")] = None,
    ) -> str:
        """Cambia una tarea: estado (p. ej. completed), prioridad, fechas, responsable,
        proyecto, espera/seguimiento… Sólo se tocan los campos que pases."""
        body: dict[str, Any] = {
            "title": title,
            "description": description,
            "status": status,
            "priority": priority,
            "scheduled_date": _opt_date(scheduled_date),
            "assigned_to": assigned_to,
            "project_id": project_id,
            "client_id": client_id,
            "estimated_minutes": estimated_minutes,
            "waiting_for": waiting_for,
            "follow_up_date": _opt_date(follow_up_date),
            "link_url": link_url,
        }
        if due_date:
            body["due_date"] = f"{_opt_date(due_date)}T00:00:00"
        body = {k: v for k, v in body.items() if v is not None}
        for field_name in clear or []:
            if field_name in body:
                raise ToolError(f"'{field_name}' no puede ir a la vez en un valor y en clear.")
            body[field_name] = None
        if not body:
            raise ToolError("No has indicado ningún cambio.")
        task = await call(client.put(f"/api/tasks/{task_id}", body))
        return f"Tarea actualizada: {fmt.task_line(task)}"

    @mcp.tool(annotations=WRITE)
    async def comment_task(task_id: int, text: Annotated[str, Field(min_length=1, max_length=2000)]) -> str:
        """Añade un comentario a una tarea."""
        await call(client.post(f"/api/tasks/{task_id}/comments", {"text": text}))
        return f"Comentario añadido a la tarea #{task_id}."

    @mcp.tool(annotations=WRITE)
    async def capture_inbox(
        text: Annotated[str, Field(min_length=1, max_length=10_000)],
        project_id: int | None = None,
        client_id: int | None = None,
        link_url: str | None = None,
    ) -> str:
        """Apunta una idea o pendiente en el inbox para procesarlo luego. The Agency la
        clasifica sola en segundo plano. Úsala cuando no esté claro que sea una tarea."""
        body = {"raw_text": text, "source": "quick_capture", "project_id": project_id,
                "client_id": client_id, "link_url": link_url}
        note = await call(client.post("/api/inbox", {k: v for k, v in body.items() if v is not None}))
        return f"Apuntado en el inbox: {fmt.inbox_line(note)}"

    @mcp.tool(annotations=WRITE)
    async def log_time(
        minutes: Annotated[int, Field(ge=1, le=24 * 60)],
        task_id: int | None = None,
        notes: str | None = None,
        day: Annotated[str | None, Field(description="Día AAAA-MM-DD. Por defecto, hoy.")] = None,
    ) -> str:
        """Registra tiempo trabajado a mano (sin temporizador)."""
        body: dict[str, Any] = {"minutes": minutes, "task_id": task_id, "notes": notes}
        if day:
            body["date"] = f"{_opt_date(day)}T00:00:00"
        entry = await call(client.post("/api/time-entries", {k: v for k, v in body.items() if v is not None}))
        what = f"#{entry['task_id']} {entry.get('task_title')}" if entry.get("task_id") else "sin tarea"
        return f"Registrado {fmt.hours(entry['minutes'])} el {fmt.day(entry.get('date'))} · {what}."

    @mcp.tool(annotations=WRITE)
    async def timer(
        action: Literal["status", "start", "pause", "resume", "stop"],
        task_id: Annotated[int | None, Field(description="Tarea al arrancar")] = None,
        notes: str | None = None,
    ) -> str:
        """Temporizador de tiempo: ver estado, arrancar (opcionalmente sobre una tarea),
        pausar, reanudar o parar (al parar se guarda la entrada de tiempo)."""
        if action == "status":
            return fmt.timer_line(await call(client.get("/api/timer/active")), tz)
        if action == "start":
            body = {k: v for k, v in {"task_id": task_id, "notes": notes}.items() if v is not None}
            return fmt.timer_line(await call(client.post("/api/timer/start", body)), tz)
        if action in ("pause", "resume"):
            return fmt.timer_line(await call(client.post(f"/api/timer/{action}")), tz)
        active = await call(client.get("/api/timer/active"))
        if not active:
            return "No hay ningún temporizador en marcha."
        body = {"timer_id": active["id"]}
        if notes:
            body["notes"] = notes
        entry = await call(client.post("/api/timer/stop", body))
        what = f"#{entry['task_id']} {entry.get('task_title')}" if entry.get("task_id") else "sin tarea"
        return f"Temporizador parado: {fmt.hours(entry.get('minutes'))} registrados · {what}."

    @mcp.tool(annotations=WRITE)
    async def submit_daily(
        text: Annotated[str, Field(min_length=1, max_length=50_000, description="Lo hecho hoy, en texto libre")],
        day: Annotated[str | None, Field(description="Día AAAA-MM-DD. Por defecto, hoy.")] = None,
    ) -> str:
        """Guarda el daily (cierre del día) de la persona y lo estructura con IA por
        proyectos, como al enviarlo en la web. Queda en borrador: no se publica en
        Discord (para eso, send_daily_to_discord). Puede tardar hasta un minuto y medio.
        Si ese día ya tiene otro daily, falla y no lo pisa."""
        body: dict[str, Any] = {"raw_text": text}
        if day:
            body["date"] = _opt_date(day)
        daily = await call(client.post("/api/dailys", body))
        if daily.get("parsed_data") is None and daily.get("status") == "draft":
            try:
                daily = await client.post(
                    f"/api/dailys/{daily['id']}/reparse", {"revision": daily["revision"]},
                    timeout=DAILY_AI_TIMEOUT,
                )
            except AgencyError as exc:
                # El texto ya está guardado: no es un fallo del daily, sólo del parseo.
                return (f"Daily #{daily['id']} del {daily['date']} guardado, pero sin estructurar ({exc}). "
                        "Se puede reintentar desde la web.")
        return fmt.daily_detail(daily)

    @mcp.tool(annotations=PUBLISH)
    async def send_daily_to_discord(daily_id: int) -> str:
        """PUBLICA en el canal de Discord del equipo un daily de la persona (sólo los
        suyos), tal y como está guardado. Es visible para todo el equipo y no se puede
        deshacer desde The Agency: confírmalo con la persona antes de usarla."""
        me = await call(client.get("/api/auth/me"))
        daily = await call(client.get(f"/api/dailys/{daily_id}"))
        if daily.get("user_id") != me["id"]:
            raise ToolError(f"El daily #{daily_id} no es tuyo: desde aquí sólo se envían los propios.")
        # Con la revisión: si alguien lo edita entre medias, el backend lo rechaza.
        receipt = await call(client.post(
            f"/api/dailys/{daily_id}/send-discord", {"revision": daily["revision"]}))
        return f"Daily #{daily_id} del {daily['date']}: {receipt.get('message')} (estado del envío: {receipt.get('status')})."

    return mcp


def _load_password(email: str) -> str:
    password = os.environ.get("AGENCY_PASSWORD")
    if password:
        return password
    # Sin variable de entorno: Llavero de macOS, para no dejar la contraseña
    # en texto plano en la configuración de Claude.
    try:
        result = subprocess.run(
            ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-a", email, "-w"],
            capture_output=True, text=True, check=False,
        )
    except FileNotFoundError:
        result = None
    if result is not None and result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip()
    sys.exit(
        "agency-mcp: falta la contraseña. Pon AGENCY_PASSWORD o guárdala en el Llavero con\n"
        f"  security add-generic-password -s {KEYCHAIN_SERVICE} -a {email} -w"
    )


def main() -> None:
    # httpx registra cada petición a INFO; en el log del MCP sólo estorba.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    email = os.environ.get("AGENCY_EMAIL")
    if not email:
        sys.exit("agency-mcp: falta AGENCY_EMAIL.")
    client = AgencyClient(
        os.environ.get("AGENCY_URL", DEFAULT_URL),
        email,
        _load_password(email),
        timeout=float(os.environ.get("AGENCY_TIMEOUT", "30")),
    )
    build_server(client, timezone=os.environ.get("AGENCY_TIMEZONE", "Europe/Madrid")).run("stdio")


if __name__ == "__main__":
    main()
