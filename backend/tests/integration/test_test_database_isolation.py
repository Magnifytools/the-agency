"""Lo que abre la sesión global durante un test va a la base de PRUEBAS.

Antes, el middleware de uso escribía `audit_logs` en la base de `.env` en cada
petición de los tests de integración (fallaba en silencio por la FK de usuario).
"""
from backend.config import settings


async def test_la_sesion_global_apunta_a_la_base_de_pruebas(engine):
    from backend.db import database

    bound = database.async_session.kw["bind"]
    assert bound.url == engine.url
    assert bound.url.render_as_string(hide_password=False) != settings.DATABASE_URL


async def test_una_peticion_no_abre_la_base_de_env(make_member_client, monkeypatch):
    from backend.db import database

    opened = []
    real_factory = database.async_session

    def spy(*args, **kwargs):
        opened.append(database.async_session.kw["bind"].url.database)
        return real_factory(*args, **kwargs)

    spy.kw = real_factory.kw
    monkeypatch.setattr(database, "async_session", spy)
    member = await make_member_client([("tasks", True, False)])

    response = await member.get("/api/incidents/count")

    assert response.status_code == 200, response.text
    # El middleware de uso abrió la sesión global... y era la de pruebas.
    assert opened, "el middleware de uso no llegó a abrir la sesión global"
    assert set(opened) == {real_factory.kw["bind"].url.database}
