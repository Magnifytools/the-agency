"""Bloques de trabajo ↔ Google Calendar contra Postgres real; Google es un falso en memoria."""
from datetime import date, datetime, timedelta, timezone
from itertools import count
from urllib.parse import parse_qs, urlsplit

import pytest
from sqlalchemy import delete, select

from backend.api.routes import google_calendar as route
from backend.db.models import Client, Task, TaskStatus, TaskTimeBlock, User, UserBlocksCalendar
from backend.services import calendar_blocks_sync as sync
from backend.services.google_calendar_service import BLOCKS_SCOPE, SCOPES
from backend.tests.integration.test_scheduled_communications import fixture, client  # noqa: F401

pytestmark = pytest.mark.integration


class _Missing(Exception):
    def __init__(self):
        self.resp = type("Resp", (), {"status": 404})()


class _Call:
    def __init__(self, fn):
        self.fn = fn

    def execute(self):
        return self.fn()


class FakeGoogle:
    """Un calendario de Google mínimo: lo justo que usa el servicio."""

    def __init__(self):
        self.items: dict[str, dict] = {}
        self.calendars: set[str] = set()
        self.writes = 0
        self._ids = count(1)

    @staticmethod
    def stamp() -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    def touch(self, event_id: str, **fields):
        """Cambio hecho a mano en Google."""
        self.items[event_id].update(fields, updated=self.stamp())

    def calendars_(self):
        fake = self

        class Calendars:
            def insert(self, body):
                calendar_id = f"agency-{next(fake._ids)}@group.calendar.google.com"
                fake.calendars.add(calendar_id)
                return _Call(lambda: {"id": calendar_id, **body})

            def delete(self, calendarId):
                return _Call(lambda: fake.calendars.discard(calendarId))
        return Calendars()

    def events(self):
        fake = self

        def civil(value: str) -> datetime:
            return datetime.fromisoformat(value).replace(tzinfo=None)

        class Events:
            def list(self, calendarId, timeMin, timeMax, pageToken=None, **_):
                low, high = civil(timeMin), civil(timeMax)
                items = [item for item in fake.items.values()
                         if "dateTime" not in item["start"] or low <= civil(item["start"]["dateTime"]) < high]
                return _Call(lambda: {"items": [dict(item) for item in items]})

            def get(self, calendarId, eventId):
                def run():
                    if eventId not in fake.items:
                        raise _Missing()
                    return dict(fake.items[eventId])
                return _Call(run)

            def insert(self, calendarId, body):
                def run():
                    fake.writes += 1
                    event_id = f"ev{next(fake._ids)}"
                    fake.items[event_id] = {**body, "id": event_id, "status": "confirmed", "updated": fake.stamp()}
                    return dict(fake.items[event_id])
                return _Call(run)

            def patch(self, calendarId, eventId, body):
                def run():
                    fake.writes += 1
                    fake.items[eventId].update(body, updated=fake.stamp())
                    return dict(fake.items[eventId])
                return _Call(run)

            def delete(self, calendarId, eventId):
                def run():
                    fake.writes += 1
                    fake.items[eventId].update(status="cancelled", updated=fake.stamp())
                return _Call(run)
        return Events()


@pytest.fixture
def google(monkeypatch):
    fake = FakeGoogle()
    service = type("Service", (), {"events": lambda self: fake.events(), "calendars": lambda self: fake.calendars_()})()
    monkeypatch.setattr(sync, "_service", lambda token: service)
    monkeypatch.setattr(sync, "business_today", lambda: date(2026, 10, 28))
    return fake


async def _publishing(fixture, google, *, blocks=((datetime(2026, 10, 29, 10), datetime(2026, 10, 29, 11, 30)),)):
    maker, ids, _ = fixture
    async with maker() as db:
        user = await db.get(User, ids["member"])
        user.google_refresh_token = "synthetic-grant"
        db.add(UserBlocksCalendar(user_id=user.id, calendar_id=sync.create_blocks_calendar("synthetic-grant")))
        customer = Client(name="Fit")
        db.add(customer)
        await db.flush()
        task = Task(title="Auditoría", status=TaskStatus.pending, client_id=customer.id, assigned_to=user.id)
        db.add(task)
        await db.flush()
        rows = [TaskTimeBlock(task_id=task.id, user_id=user.id, starts_at=start, ends_at=end) for start, end in blocks]
        db.add_all(rows)
        await db.commit()
        return task.id, [row.id for row in rows], customer.id


async def _block(maker, block_id):
    async with maker() as db:
        return await db.get(TaskTimeBlock, block_id)


async def _cleanup(maker, customer_id):
    async with maker() as db:
        await db.execute(delete(Task).where(Task.client_id == customer_id))
        await db.execute(delete(Client).where(Client.id == customer_id))
        await db.commit()


async def test_publica_el_bloque_y_una_segunda_pasada_no_escribe(fixture, google):
    maker, ids, _ = fixture
    task_id, (block_id,), customer_id = await _publishing(fixture, google)
    result = await sync.sync_user(maker, ids["member"])
    assert result["created"] == 1
    row = await _block(maker, block_id)
    event = google.items[row.google_event_id]
    assert event["summary"] == "Auditoría · Fit"
    assert event["extendedProperties"]["private"]["agency_block_id"] == str(block_id)
    assert event["start"] == {"dateTime": "2026-10-29T10:00:00", "timeZone": "Europe/Madrid"}
    assert f"/tasks?task={task_id}" in event["description"]
    assert row.google_synced_at == row.updated_at

    writes = google.writes
    assert not any((await sync.sync_user(maker, ids["member"])).values())
    assert google.writes == writes
    await _cleanup(maker, customer_id)


async def test_mover_en_la_app_y_mover_en_google(fixture, google):
    maker, ids, _ = fixture
    _, (block_id,), customer_id = await _publishing(fixture, google)
    await sync.sync_user(maker, ids["member"])

    async with maker() as db:
        row = await db.get(TaskTimeBlock, block_id)
        row.starts_at, row.ends_at = datetime(2026, 10, 30, 16), datetime(2026, 10, 30, 17)
        await db.commit()
    assert (await sync.sync_user(maker, ids["member"]))["patched"] == 1
    event_id = (await _block(maker, block_id)).google_event_id
    assert google.items[event_id]["start"]["dateTime"] == "2026-10-30T16:00:00"

    google.touch(event_id, start={"dateTime": "2026-10-30T08:00:00Z"}, end={"dateTime": "2026-10-30T10:00:00Z"})
    assert (await sync.sync_user(maker, ids["member"]))["from_google"] == 1
    row = await _block(maker, block_id)
    assert (row.starts_at, row.ends_at) == (datetime(2026, 10, 30, 9), datetime(2026, 10, 30, 11))  # hora de Madrid
    # Después no rebota: ni la app ni Google tienen nada nuevo.
    assert not any((await sync.sync_user(maker, ids["member"])).values())
    await _cleanup(maker, customer_id)


async def test_un_cambio_en_google_que_no_es_un_bloque_se_deshace(fixture, google):
    maker, ids, _ = fixture
    _, (block_id,), customer_id = await _publishing(fixture, google)
    await sync.sync_user(maker, ids["member"])
    event_id = (await _block(maker, block_id)).google_event_id
    google.touch(event_id, end={"dateTime": "2026-10-30T12:00:00", "timeZone": "Europe/Madrid"})
    assert (await sync.sync_user(maker, ids["member"]))["patched"] == 1
    assert google.items[event_id]["end"]["dateTime"] == "2026-10-29T11:30:00"
    assert (await _block(maker, block_id)).ends_at == datetime(2026, 10, 29, 11, 30)
    await _cleanup(maker, customer_id)


async def test_borrar_en_google_borra_el_bloque_y_no_la_tarea(fixture, google):
    maker, ids, _ = fixture
    task_id, (block_id,), customer_id = await _publishing(fixture, google)
    await sync.sync_user(maker, ids["member"])
    google.touch((await _block(maker, block_id)).google_event_id, status="cancelled")
    assert (await sync.sync_user(maker, ids["member"]))["deleted_blocks"] == 1
    assert await _block(maker, block_id) is None
    async with maker() as db:
        assert await db.get(Task, task_id) is not None
    await _cleanup(maker, customer_id)


async def test_borrar_en_la_app_borra_el_evento_y_no_toca_los_ajenos(fixture, google):
    maker, ids, _ = fixture
    _, (block_id,), customer_id = await _publishing(fixture, google)
    await sync.sync_user(maker, ids["member"])
    google.items["ajeno"] = {"id": "ajeno", "status": "confirmed", "updated": google.stamp(),
                             "start": {"dateTime": "2026-10-29T12:00:00"}, "end": {"dateTime": "2026-10-29T13:00:00"}}
    event_id = (await _block(maker, block_id)).google_event_id
    async with maker() as db:
        await db.delete(await db.get(TaskTimeBlock, block_id))
        await db.commit()
    assert (await sync.sync_user(maker, ids["member"]))["deleted_events"] == 1
    assert google.items[event_id]["status"] == "cancelled"
    assert google.items["ajeno"]["status"] == "confirmed"
    await _cleanup(maker, customer_id)


async def test_mover_fuera_de_la_ventana_no_borra_nada(fixture, google):
    maker, ids, _ = fixture
    _, (block_id,), customer_id = await _publishing(fixture, google)
    await sync.sync_user(maker, ids["member"])
    event_id = (await _block(maker, block_id)).google_event_id
    # En Google, a dentro de dos meses: no sale en la lista, pero existe.
    google.touch(event_id, start={"dateTime": "2026-12-29T10:00:00"}, end={"dateTime": "2026-12-29T11:00:00"})
    assert (await sync.sync_user(maker, ids["member"]))["from_google"] == 1
    assert (await _block(maker, block_id)).starts_at == datetime(2026, 12, 29, 10)
    # Y vuelta a la ventana desde la app: el evento la sigue.
    async with maker() as db:
        row = await db.get(TaskTimeBlock, block_id)
        row.starts_at, row.ends_at = datetime(2026, 10, 29, 10), datetime(2026, 10, 29, 11)
        await db.commit()
    assert (await sync.sync_user(maker, ids["member"]))["patched"] == 1
    assert google.items[event_id]["start"]["dateTime"] == "2026-10-29T10:00:00"
    await _cleanup(maker, customer_id)


async def test_activar_pide_los_dos_permisos_y_crea_el_calendario(fixture, google, monkeypatch):
    maker, ids, _ = fixture
    monkeypatch.setattr(route.settings, "GOOGLE_CLIENT_ID", "synthetic-client")
    monkeypatch.setattr(route.settings, "GOOGLE_CLIENT_SECRET", "synthetic-secret")
    async with client(fixture) as http:
        url = (await http.get("/api/calendar/blocks/auth-url")).json()["url"]
        query = parse_qs(urlsplit(url).query)
        assert query["scope"] == [" ".join([*SCOPES, BLOCKS_SCOPE])]
        state = query["state"][0]

        monkeypatch.setattr(route, "exchange_code", lambda code: {"refresh_token": "grant", "scope": SCOPES[0]})
        response = await http.get("/api/calendar/callback", params={"code": "x", "state": state})
        assert response.headers["location"] == "/settings?calendar=blocks_denied"
        assert (await http.get("/api/calendar/status")).json()["blocks_calendar"] is False

        monkeypatch.setattr(route, "create_blocks_calendar", lambda token: "agency-cal")
        monkeypatch.setattr(route, "exchange_code",
                            lambda code: {"refresh_token": "grant", "scope": f"{SCOPES[0]} {BLOCKS_SCOPE}"})
        response = await http.get("/api/calendar/callback", params={"code": "x", "state": state})
        assert response.headers["location"] == "/settings?calendar=blocks_on"
        assert (await http.get("/api/calendar/status")).json()["blocks_calendar"] is True
        # Reconectar a secas sigue pidiendo el permiso de los bloques.
        url = (await http.get("/api/calendar/auth-url")).json()["url"]
        assert BLOCKS_SCOPE in parse_qs(urlsplit(url).query)["scope"][0]
    async with maker() as db:
        assert await sync.blocks_calendar_id(db, ids["member"]) == "agency-cal"


async def test_desactivar_puede_borrar_el_calendario(fixture, google, monkeypatch):
    maker, ids, _ = fixture
    _, (block_id,), customer_id = await _publishing(fixture, google)
    await sync.sync_user(maker, ids["member"])
    async with maker() as db:
        calendar_id = await sync.blocks_calendar_id(db, ids["member"])
    before = (await _block(maker, block_id)).updated_at
    monkeypatch.setattr(route, "delete_blocks_calendar", lambda token, cal: google.calendars.discard(cal))
    async with client(fixture) as http:
        response = await http.post("/api/calendar/blocks/disable", json={"delete_calendar": True})
        assert response.json() == {"ok": True, "calendar_deleted": True}
    assert calendar_id not in google.calendars
    row = await _block(maker, block_id)
    assert (row.google_event_id, row.google_synced_at, row.updated_at) == (None, None, before)
    async with maker() as db:
        assert await sync.blocks_calendar_id(db, ids["member"]) is None
    await _cleanup(maker, customer_id)


async def test_desconectar_borra_el_calendario_antes_de_revocar(fixture, google, monkeypatch):
    maker, ids, _ = fixture
    _, _, customer_id = await _publishing(fixture, google)
    order = []
    monkeypatch.setattr(route, "delete_blocks_calendar", lambda token, cal: order.append("calendar"))

    async def revoke(token):
        order.append("revoke")
        return True
    monkeypatch.setattr(route, "revoke_token", revoke)
    async with maker() as db:
        user = await db.get(User, ids["member"])
        user.google_refresh_token = route.encrypt_refresh_token("synthetic-grant")
        await db.commit()
    async with client(fixture) as http:
        body = (await http.post("/api/calendar/disconnect", json={"delete_blocks_calendar": True})).json()
    assert body["blocks_calendar_deleted"] is True and order == ["calendar", "revoke"]
    async with maker() as db:
        assert await sync.blocks_calendar_id(db, ids["member"]) is None
        assert (await db.execute(select(TaskTimeBlock.google_event_id).where(
            TaskTimeBlock.user_id == ids["member"], TaskTimeBlock.google_event_id.is_not(None)))).first() is None
    await _cleanup(maker, customer_id)


async def test_si_borra_el_calendario_en_google_deja_de_publicar(fixture, google, monkeypatch):
    maker, ids, _ = fixture
    _, (block_id,), customer_id = await _publishing(fixture, google)
    await sync.sync_user(maker, ids["member"])

    def gone(*args, **kwargs):
        raise _Missing()
    monkeypatch.setattr(sync, "list_block_events", gone)
    assert await sync.sync_user(maker, ids["member"]) == {"calendar_gone": 1}
    async with maker() as db:
        assert await sync.blocks_calendar_id(db, ids["member"]) is None
    row = await _block(maker, block_id)
    assert row is not None and row.google_event_id is None  # el bloque sigue en Mi agenda
    await _cleanup(maker, customer_id)


async def test_desactivar_a_mitad_de_pasada_no_resucita_la_relacion(fixture, google, monkeypatch):
    maker, ids, _ = fixture
    _, (block_id,), customer_id = await _publishing(fixture, google)
    import anyio
    real_run_sync, calls = anyio.to_thread.run_sync, []

    async def run_sync_then_disable(func, *args, **kwargs):
        result = await real_run_sync(func, *args, **kwargs)
        calls.append(func)
        if len(calls) == 2:  # tras escribir en Google y antes de guardar
            async with maker() as db:
                await sync.forget_blocks(db, ids["member"])
                await db.commit()
        return result
    monkeypatch.setattr(anyio.to_thread, "run_sync", run_sync_then_disable)
    await sync.sync_user(maker, ids["member"])
    assert (await _block(maker, block_id)).google_event_id is None
    await _cleanup(maker, customer_id)
