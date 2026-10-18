"""Tests del servidor MCP contra un backend falso (httpx.MockTransport).

Se prueba lo que el servidor añade sobre la API: sesión y re-login, qué se
manda en cada llamada y cómo se le cuenta el resultado o el error al modelo.
"""

from __future__ import annotations

import json
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
import pytest
from agency_mcp.client import AgencyClient
from agency_mcp.server import build_server
from mcp import Client

TASK = {
    "id": 7, "title": "Keyword research", "status": "in_progress", "priority": "high",
    "client_name": "Fit Generation", "project_name": "SEO 2026", "assigned_user_name": "David",
    "due_date": "2026-10-20T00:00:00", "scheduled_date": "2026-10-18",
}


class FakeAgency:
    """Backend mínimo: rutas -> respuestas, y registro de todo lo recibido."""

    def __init__(self):
        self.requests: list[httpx.Request] = []
        self.routes: dict[tuple[str, str], object] = {}
        self.logins = 0
        self.valid_tokens = {"tok-1"}
        self.next_token = "tok-1"

    def route(self, method: str, path: str, response):
        self.routes[(method, path)] = response

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path == "/api/auth/login":
            self.logins += 1
            body = json.loads(request.content)
            if body["password"] != "secreto":
                return httpx.Response(401, json={"detail": "Invalid credentials"})
            return httpx.Response(
                200, json={"access_token": self.next_token},
                headers={"set-cookie": "agency_session=cookie; Path=/"},
            )
        token = request.headers.get("authorization", "").removeprefix("Bearer ")
        if token not in self.valid_tokens:
            return httpx.Response(401, json={"detail": "Invalid token"})
        key = (request.method, request.url.path)
        if key not in self.routes:
            return httpx.Response(404, json={"detail": "Not found"})
        response = self.routes[key]
        if callable(response):
            response = response(request)
        if isinstance(response, httpx.Response):
            return response
        # FastAPI devuelve `null` (no un cuerpo vacío) para un Optional a None.
        return httpx.Response(200, content=json.dumps(response).encode(),
                              headers={"content-type": "application/json"})

    def last(self, method: str, path: str) -> httpx.Request:
        return [r for r in self.requests if r.method == method and r.url.path == path][-1]


@pytest.fixture
def fake():
    return FakeAgency()


@pytest.fixture
def agency(fake):
    return AgencyClient("http://agency.test", "david@magnify.ing", "secreto",
                        transport=httpx.MockTransport(fake.handler))


async def call(agency, tool, args=None):
    async with Client(build_server(agency)) as client:
        result = await client.call_tool(tool, args or {})
    text = "\n".join(c.text for c in result.content if hasattr(c, "text"))
    return result.is_error, text


# ── Sesión ─────────────────────────────────────────────────────────────


async def test_entra_una_vez_y_manda_bearer_sin_cookies(fake, agency):
    fake.route("GET", "/api/timer/active", None)
    await call(agency, "timer", {"action": "status"})
    await call(agency, "timer", {"action": "status"})

    assert fake.logins == 1
    req = fake.last("GET", "/api/timer/active")
    assert req.headers["authorization"] == "Bearer tok-1"
    # Con cookie de sesión y sin CSRF el backend rechazaría las escrituras.
    assert "cookie" not in req.headers


async def test_token_caducado_vuelve_a_entrar_y_repite(fake, agency):
    fake.route("GET", "/api/timer/active", None)
    await call(agency, "timer", {"action": "status"})
    fake.valid_tokens = {"tok-2"}
    fake.next_token = "tok-2"

    is_error, text = await call(agency, "timer", {"action": "status"})

    assert not is_error, text
    assert fake.logins == 2
    assert fake.last("GET", "/api/timer/active").headers["authorization"] == "Bearer tok-2"


async def test_credenciales_malas_dan_un_error_legible(fake):
    bad = AgencyClient("http://agency.test", "david@magnify.ing", "otra",
                       transport=httpx.MockTransport(fake.handler))
    is_error, text = await call(bad, "timer", {"action": "status"})

    assert is_error
    assert "No se pudo iniciar sesión" in text and "Invalid credentials" in text


async def test_errores_de_validacion_llegan_con_el_campo(fake, agency):
    fake.route("POST", "/api/tasks", httpx.Response(422, json={"detail": [
        {"loc": ["body", "project_id"], "msg": "Proyecto no encontrado"}]}))
    is_error, text = await call(agency, "create_task", {"title": "x", "project_id": 999})

    assert is_error
    assert "project_id: Proyecto no encontrado" in text


# ── Lectura ────────────────────────────────────────────────────────────


async def test_agenda_de_hoy_usa_el_dia_de_madrid(fake, agency):
    def agenda(request):
        section = request.url.params["section"]
        items = [TASK] if section == "planned" else []
        return {"items": items, "total": len(items), "page": 1, "page_size": 50}

    fake.route("GET", "/api/tasks/agenda", agenda)
    fake.route("GET", "/api/timer/active", None)
    fake.route("GET", "/api/inbox/count", {"count": 3})

    is_error, text = await call(agency, "today_agenda")

    assert not is_error, text
    today = datetime.now(ZoneInfo("Europe/Madrid")).date().isoformat()
    sections = [r.url.params["section"] for r in fake.requests if r.url.path == "/api/tasks/agenda"]
    assert sections == ["planned", "carryover", "completed"]
    req = fake.last("GET", "/api/tasks/agenda")
    assert req.url.params["date"] == today and req.url.params["assigned_to"] == "me"
    assert "#7 Keyword research [en curso · alta]" in text
    assert "Fit Generation / SEO 2026" in text
    assert "3 notas por procesar" in text


async def test_list_tasks_por_defecto_abiertas_y_mias(fake, agency):
    fake.route("GET", "/api/tasks", {"items": [TASK], "total": 40, "page": 1, "page_size": 30})
    _is_error, text = await call(agency, "list_tasks")

    params = fake.last("GET", "/api/tasks").url.params
    assert "completed" not in params["status"] and "in_progress" in params["status"]
    assert params["assigned_to"] == "me"
    assert "40 tareas, se muestran 1" in text


async def test_list_tasks_all_no_filtra_por_persona(fake, agency):
    fake.route("GET", "/api/tasks", {"items": [], "total": 0, "page": 1, "page_size": 30})
    await call(agency, "list_tasks", {"assigned_to": "all", "status": ["completed"]})

    params = fake.last("GET", "/api/tasks").url.params
    assert "assigned_to" not in params
    assert params["status"] == "completed"


async def test_get_task_junta_checklist_y_comentarios(fake, agency):
    fake.route("GET", "/api/tasks/7", {**TASK, "description": "Semillas y clusters"})
    fake.route("GET", "/api/tasks/7/checklist", [
        {"id": 1, "text": "Copiar plantilla", "is_done": True},
        {"id": 2, "text": "Definir semillas", "is_done": False}])
    fake.route("GET", "/api/tasks/7/comments", [
        {"id": 1, "text": "Ojo con la marca", "user_name": "Nacho", "created_at": "2026-10-17T10:00:00"}])

    _, text = await call(agency, "get_task", {"task_id": 7})

    assert "Checklist (1/2)" in text and "- [x] Copiar plantilla" in text
    assert "Nacho: Ojo con la marca" in text
    assert "Semillas y clusters" in text


async def test_horas_suman_por_cliente(fake, agency):
    fake.route("GET", "/api/time-entries", [
        {"id": 1, "minutes": 90, "date": "2026-10-13T00:00:00", "task_id": 7, "task_title": "KW", "client_name": "FG"},
        {"id": 2, "minutes": 30, "date": "2026-10-14T00:00:00", "task_id": None, "client_name": "FG"},
        {"id": 3, "minutes": 45, "date": "2026-10-14T00:00:00", "task_id": 8, "task_title": "Audit", "client_name": "Dicas"}])

    _, text = await call(agency, "list_time_entries", {"date_from": "2026-10-13", "date_to": "2026-10-17"})

    params = fake.last("GET", "/api/time-entries").url.params
    assert params["date_from"] == "2026-10-13T00:00:00"
    assert params["date_to"] == "2026-10-17T23:59:59"
    assert text.startswith("2 h 45 min entre 2026-10-13 y 2026-10-17")
    assert "- FG: 2 h" in text and "- Dicas: 45 min" in text


# ── Escritura ──────────────────────────────────────────────────────────


async def test_create_task_sin_responsable_se_asigna_a_quien_llama(fake, agency):
    fake.route("POST", "/api/tasks", TASK)
    _is_error, text = await call(agency, "create_task", {
        "title": "Keyword research", "project_id": 3, "due_date": "2026-10-20"})

    body = json.loads(fake.last("POST", "/api/tasks").content)
    assert body["assign_to_current_user"] is True and "assigned_to" not in body
    assert body["due_date"] == "2026-10-20T00:00:00"
    assert body["project_id"] == 3
    assert "description" not in body  # no se mandan nulos
    assert text.startswith("Tarea creada: #7")


async def test_create_task_con_responsable(fake, agency):
    fake.route("POST", "/api/tasks", TASK)
    await call(agency, "create_task", {"title": "x", "assigned_to": 2})

    body = json.loads(fake.last("POST", "/api/tasks").content)
    assert body["assigned_to"] == 2 and "assign_to_current_user" not in body


async def test_fecha_mal_escrita_no_llega_al_backend(fake, agency):
    is_error, _text = await call(agency, "create_task", {"title": "x", "due_date": "20/10/2026"})

    assert is_error
    assert not [r for r in fake.requests if r.url.path == "/api/tasks"]


async def test_update_task_solo_manda_lo_indicado_y_vacia_con_clear(fake, agency):
    fake.route("PUT", "/api/tasks/7", {**TASK, "status": "waiting", "waiting_for": "cliente"})
    _is_error, text = await call(agency, "update_task", {
        "task_id": 7, "status": "waiting", "waiting_for": "cliente", "clear": ["due_date"]})

    body = json.loads(fake.last("PUT", "/api/tasks/7").content)
    assert body == {"status": "waiting", "waiting_for": "cliente", "due_date": None}
    assert "esperando a cliente" in text


async def test_update_task_sin_cambios_o_contradictorio_falla(fake, agency):
    is_error, text = await call(agency, "update_task", {"task_id": 7})
    assert is_error and "ningún cambio" in text

    is_error, text = await call(agency, "update_task", {
        "task_id": 7, "due_date": "2026-10-20", "clear": ["due_date"]})
    assert is_error and "a la vez" in text
    assert not [r for r in fake.requests if r.method == "PUT"]


async def test_capture_inbox(fake, agency):
    fake.route("POST", "/api/inbox", {"id": 5, "raw_text": "Probar anuncios", "status": "pending",
                                      "created_at": "2026-10-18T09:00:00"})
    _, text = await call(agency, "capture_inbox", {"text": "Probar anuncios"})

    body = json.loads(fake.last("POST", "/api/inbox").content)
    assert body == {"raw_text": "Probar anuncios", "source": "quick_capture"}
    assert "#5 [pending] Probar anuncios" in text


async def test_log_time_con_dia(fake, agency):
    fake.route("POST", "/api/time-entries", {"id": 1, "minutes": 75, "date": "2026-10-17T00:00:00",
                                             "task_id": 7, "task_title": "KW"})
    _, text = await call(agency, "log_time", {"minutes": 75, "task_id": 7, "day": "2026-10-17"})

    body = json.loads(fake.last("POST", "/api/time-entries").content)
    assert body == {"minutes": 75, "task_id": 7, "date": "2026-10-17T00:00:00"}
    assert text == "Registrado 1 h 15 min el 2026-10-17 · #7 KW."


async def test_parar_temporizador_identifica_el_que_esta_en_marcha(fake, agency):
    fake.route("GET", "/api/timer/active", {"id": 42, "task_id": 7, "task_title": "KW",
                                            "started_at": "2026-10-18T09:00:00", "is_paused": False})
    fake.route("POST", "/api/timer/stop", {"id": 9, "minutes": 50, "task_id": 7, "task_title": "KW"})

    _, text = await call(agency, "timer", {"action": "stop"})

    assert json.loads(fake.last("POST", "/api/timer/stop").content) == {"timer_id": 42}
    assert text == "Temporizador parado: 50 min registrados · #7 KW."


async def test_parar_sin_temporizador_no_llama_a_stop(fake, agency):
    fake.route("GET", "/api/timer/active", None)
    _, text = await call(agency, "timer", {"action": "stop"})

    assert text == "No hay ningún temporizador en marcha."
    assert not [r for r in fake.requests if r.url.path == "/api/timer/stop"]


def test_no_hay_herramientas_de_borrado(agency):
    import asyncio

    async def names():
        async with Client(build_server(agency)) as client:
            return [t.name for t in (await client.list_tools()).tools]

    assert not [n for n in asyncio.run(names()) if "delete" in n or "remove" in n]


def test_hora_del_temporizador_en_hora_de_madrid():
    from agency_mcp.format import local_time

    madrid = ZoneInfo("Europe/Madrid")
    # 18 oct 2026 aún es horario de verano: UTC+2
    assert local_time("2026-10-17T06:42:20.175164Z", madrid) == "2026-10-17 08:42"
    assert local_time("2026-10-17T06:42:20", madrid) == "2026-10-17 08:42"  # sin zona = UTC
