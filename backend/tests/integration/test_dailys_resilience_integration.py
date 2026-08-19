"""Integración: enviar un daily no puede perder el texto del usuario.

`POST /api/dailys` llamaba a Claude ANTES de insertar la fila. Dos consecuencias
medidas en producción (auditoría de agosto: 6 errores de 46 peticiones, 13 %, y
4.713 ms de media — el peor ratio de la aplicación):

  1. Si la IA fallaba, el usuario recibía un 502 y su daily **no se guardaba**.
  2. El cliente aborta a los 30 s (`axios timeout`), pero el SDK de Anthropic
     podía tardar hasta 180 s (60 s × 3 intentos). El navegador cortaba, el
     servidor terminaba guardando, y el reintento del usuario chocaba con el
     409 de "ya existe un daily para hoy".

Ahora la fila se guarda primero y el parseo es un enriquecimiento opcional.
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import select

from backend.db.models import DailyUpdate


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """El limitador de IA es un singleton en memoria compartido por todo el
    proceso: sin resetearlo, el sexto POST de este fichero se llevaría un 429
    de un test anterior."""
    from backend.core.rate_limiter import ai_limiter

    ai_limiter._limiter._requests.clear()
    yield


async def _dailys_de(db_session, user_id: int) -> list[DailyUpdate]:
    result = await db_session.execute(
        select(DailyUpdate).where(DailyUpdate.user_id == user_id)
    )
    return list(result.scalars().all())


@pytest.mark.asyncio
async def test_si_la_ia_falla_el_daily_se_guarda_igual(admin_client, db_session, monkeypatch):
    from backend.api.routes import dailys as dailys_route

    async def _revienta(_raw_text):
        raise RuntimeError("Anthropic caída")

    monkeypatch.setattr(dailys_route, "parse_daily_update", _revienta)

    resp = await admin_client.post(
        "/api/dailys", json={"raw_text": "Cliente Acme:\n- Auditoría técnica"}
    )

    assert resp.status_code == 201, resp.text
    assert resp.json()["parsed_data"] is None

    guardados = await _dailys_de(db_session, admin_client.test_user.id)
    assert len(guardados) == 1
    assert guardados[0].raw_text == "Cliente Acme:\n- Auditoría técnica"


@pytest.mark.asyncio
async def test_si_la_ia_devuelve_basura_tampoco_se_pierde(admin_client, db_session, monkeypatch):
    """`parse_daily_update` levanta ValueError cuando Claude no devuelve JSON."""
    from backend.api.routes import dailys as dailys_route

    async def _json_invalido(_raw_text):
        raise ValueError("La respuesta de Claude no es JSON valido")

    monkeypatch.setattr(dailys_route, "parse_daily_update", _json_invalido)

    resp = await admin_client.post("/api/dailys", json={"raw_text": "algo hice hoy"})

    assert resp.status_code == 201, resp.text
    assert len(await _dailys_de(db_session, admin_client.test_user.id)) == 1


@pytest.mark.asyncio
async def test_cuando_la_ia_responde_se_guarda_lo_parseado(admin_client, db_session, monkeypatch):
    from backend.api.routes import dailys as dailys_route

    async def _ok(_raw_text):
        return {
            "projects": [{"name": "SEO", "client": "Acme", "tasks": [
                {"description": "Auditoría técnica", "details": ""}
            ]}],
            "general": [],
            "tomorrow": ["Terminar el informe"],
        }

    monkeypatch.setattr(dailys_route, "parse_daily_update", _ok)

    resp = await admin_client.post("/api/dailys", json={"raw_text": "Acme: auditoría"})

    assert resp.status_code == 201, resp.text
    assert resp.json()["parsed_data"]["projects"][0]["client"] == "Acme"

    guardados = await _dailys_de(db_session, admin_client.test_user.id)
    assert guardados[0].parsed_data is not None


@pytest.mark.asyncio
async def test_el_daily_duplicado_sigue_devolviendo_409(admin_client, monkeypatch):
    """El 409 es correcto y se mantiene; lo que cambia es que ya casi no se
    provoca solo, porque la respuesta ya no tarda más que el timeout del cliente."""
    from backend.api.routes import dailys as dailys_route

    async def _ok(_raw_text):
        return {"projects": [], "general": [], "tomorrow": []}

    monkeypatch.setattr(dailys_route, "parse_daily_update", _ok)

    primero = await admin_client.post("/api/dailys", json={"raw_text": "uno"})
    assert primero.status_code == 201, primero.text

    segundo = await admin_client.post("/api/dailys", json={"raw_text": "dos"})
    assert segundo.status_code == 409
    assert date.today().isoformat() in segundo.json()["detail"]


@pytest.mark.asyncio
async def test_un_daily_sin_parsear_se_puede_reparsear_despues(admin_client, monkeypatch):
    """La salida para el usuario cuando la IA falló: el botón de re-parsear."""
    from backend.api.routes import dailys as dailys_route

    async def _revienta(_raw_text):
        raise RuntimeError("Anthropic caída")

    monkeypatch.setattr(dailys_route, "parse_daily_update", _revienta)
    creado = await admin_client.post("/api/dailys", json={"raw_text": "Acme: auditoría"})
    daily_id = creado.json()["id"]

    async def _ok(_raw_text):
        return {"projects": [], "general": [{"description": "Auditoría", "details": ""}], "tomorrow": []}

    monkeypatch.setattr(dailys_route, "parse_daily_update", _ok)
    reparseado = await admin_client.post(f"/api/dailys/{daily_id}/reparse")

    assert reparseado.status_code == 200, reparseado.text
    assert reparseado.json()["parsed_data"]["general"][0]["description"] == "Auditoría"
