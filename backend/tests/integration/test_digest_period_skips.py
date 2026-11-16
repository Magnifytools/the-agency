"""Saltar el periodo de un resumen (sugerencia #5 de Nacho) contra Postgres real.

Un periodo saltado deja de estar pendiente en todo lo que hoy lo decide:
avisos (``report_pending``/``report_unsent`` y su visibilidad), la cifra de la
fila Operación, el estado del cliente y "Para entregar".
"""
from datetime import date, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select

from backend.db.models import (
    Client,
    ClientReportPolicy,
    ClientStatus,
    DigestExternalDeliveryEvent,
    DigestPeriodSkip,
    ExternalDeliveryAction,
    Notification,
    User,
    UserPermission,
    UserRole,
    WeeklyDigest,
)
from backend.services.client_status import Viewer, portfolio
from backend.services.incident_report_conditions import (
    collect_report_conditions,
    report_visibility_clause,
    unsent_monthly_clients,
)
from backend.services.incidents import reconcile_recipient
from backend.services.report_policy import preview_items

pytestmark = pytest.mark.integration

NOW = datetime(2026, 10, 1, 8)  # noqa: DTZ001 - primer día laborable de octubre
SEPT = (date(2026, 9, 1), date(2026, 9, 30))
URL = "/api/digests/period-skips"
BODY = {"period_start": "2026-09-01", "period_end": "2026-09-30", "reason": "Vacaciones"}


async def _member(db, *, write=True):
    user = User(email=f"skip-{uuid4().hex}@test.local", full_name="Responsable", hashed_password="x",
                role=UserRole.member, is_active=True)
    db.add(user)
    await db.flush()
    db.add(UserPermission(user_id=user.id, module="digests", can_read=True, can_write=write))
    await db.flush()
    return user


async def _client(db, responsible, *, weekly=False, monthly=True):
    client = Client(name=f"Cliente {uuid4().hex[:8]}", status=ClientStatus.active)
    db.add(client)
    await db.flush()
    db.add(ClientReportPolicy(client_id=client.id, weekly_enabled=weekly, monthly_enabled=monthly,
                              responsible_user_id=responsible.id))
    await db.flush()
    return client


async def _kinds(db, user_id, client_id):
    return sorted(c.kind for c in (await collect_report_conditions(db, user_id, NOW)).values()
                  if c.entity_id == client_id)


async def test_saltar_quita_los_avisos_y_volver_a_pendiente_los_trae(db_session, admin_user, admin_client):
    owner = await _member(db_session)
    client = await _client(db_session, owner)
    # El admin oye que falta el mes; el responsable, que lo prepare.
    assert await _kinds(db_session, admin_user.id, client.id) == ["report_unsent"]
    assert await _kinds(db_session, owner.id, client.id) == ["report_pending"]
    await reconcile_recipient(db_session, admin_user.id, now=NOW)

    response = await admin_client.post(URL, json={"client_id": client.id, **BODY})
    assert response.status_code == 200, response.text
    skip = response.json()
    assert skip["reason"] == "Vacaciones" and skip["skipped_by_name"] == admin_user.full_name

    assert await _kinds(db_session, admin_user.id, client.id) == []
    assert await _kinds(db_session, owner.id, client.id) == []
    # La campana deja de enseñar lo ya guardado (la visibilidad lo revoca al momento).
    live = (await db_session.execute(select(Notification.type).where(
        Notification.entity_id == client.id,
        report_visibility_clause(admin_user.id, current_only=True, now=NOW),
    ))).scalars().all()
    assert live == []
    # Fila Operación: ya no es un mensual sin entregar.
    _, _, rows = await unsent_monthly_clients(db_session, admin_user.id, NOW.date())
    assert client.id not in [row.id for row in rows]

    # Idempotente: saltarlo otra vez devuelve el mismo salto.
    again = await admin_client.post(URL, json={"client_id": client.id, **BODY, "reason": "Otra cosa"})
    assert again.json()["id"] == skip["id"] and again.json()["reason"] == "Vacaciones"

    assert (await admin_client.delete(f"{URL}/{skip['id']}")).status_code == 204
    assert await _kinds(db_session, admin_user.id, client.id) == ["report_unsent"]
    assert await _kinds(db_session, owner.id, client.id) == ["report_pending"]
    assert (await admin_client.delete(f"{URL}/{skip['id']}")).status_code == 404


async def test_saltar_una_semana_no_toca_el_mes(db_session, admin_user, admin_client):
    owner = await _member(db_session)
    client = await _client(db_session, owner, weekly=True)
    week = (date(2026, 9, 21), date(2026, 9, 27))  # la última semana cerrada a 1 de octubre
    response = await admin_client.post(URL, json={"client_id": client.id, "period_start": week[0].isoformat(),
                                                  "period_end": week[1].isoformat(), "reason": "Vacaciones"})
    assert response.status_code == 200, response.text
    conditions = [c for c in (await collect_report_conditions(db_session, owner.id, NOW)).values()
                  if c.entity_id == client.id]
    assert [c.key for c in conditions] == [f"report_pending:client:{client.id}:monthly:2026-09-01:2026-09-30"]


@pytest.mark.parametrize("body, status, code", [
    ({"period_start": "2026-09-02", "period_end": "2026-09-30"}, 422, "invalid_period"),
    ({"period_start": "2099-01-01", "period_end": "2099-01-31"}, 422, "open_period"),
    ({"reason": "   "}, 422, "invalid_reason"),
])
async def test_validaciones(db_session, admin_user, admin_client, body, status, code):
    client = await _client(db_session, admin_user)
    response = await admin_client.post(URL, json={"client_id": client.id, **BODY, **body})
    assert response.status_code == status
    assert response.json()["detail"]["code"] == code


async def test_un_periodo_entregado_no_se_salta(db_session, admin_user, admin_client):
    client = await _client(db_session, admin_user)
    digest = WeeklyDigest(client_id=client.id, period_start=SEPT[0], period_end=SEPT[1], created_by=admin_user.id)
    db_session.add(digest)
    await db_session.flush()
    db_session.add(DigestExternalDeliveryEvent(digest_id=digest.id, action=ExternalDeliveryAction.confirmed,
                                               actor_id=admin_user.id, request_key=uuid4().hex,
                                               request_hash="a" * 64, created_at=NOW))
    await db_session.flush()
    response = await admin_client.post(URL, json={"client_id": client.id, **BODY})
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "already_delivered"


async def test_salta_el_responsable_y_no_otro_miembro(db_session, admin_user, make_member_client):
    stranger = await make_member_client([("digests", True, True)])
    owner_http = await make_member_client([("digests", True, True)])
    client = await _client(db_session, owner_http.test_user)
    assert (await stranger.post(URL, json={"client_id": client.id, **BODY})).status_code == 403
    response = await owner_http.post(URL, json={"client_id": client.id, **BODY})
    assert response.status_code == 200, response.text
    # Sólo lectura de resúmenes: ni saltar ni volver a pendiente.
    reader = await make_member_client([("digests", True, False)])
    assert (await reader.delete(f"{URL}/{response.json()['id']}")).status_code == 403
    assert (await stranger.delete(f"{URL}/{response.json()['id']}")).status_code == 403


async def test_el_estado_del_cliente_lo_da_por_cubierto(db_session, admin_user):
    client = await _client(db_session, admin_user)
    viewer = Viewer(is_admin=True, tasks=True, digests=True, timesheet=True)
    late = (await portfolio(db_session, [client], viewer, today=date(2026, 10, 9)))[0]
    assert late["digest"]["state"] == "late"
    db_session.add(DigestPeriodSkip(client_id=client.id, period_start=SEPT[0], period_end=SEPT[1],
                                    reason="Vacaciones", skipped_by=admin_user.id))
    await db_session.flush()
    covered = (await portfolio(db_session, [client], viewer, today=date(2026, 10, 9)))[0]
    assert covered["digest"]["state"] == "ok"


async def test_para_entregar_lo_ensena_saltado_salvo_que_se_entregue(db_session, admin_user, monkeypatch):
    monkeypatch.setattr("backend.services.report_policy.policy_digest_period", lambda cadence: SEPT)
    client = await _client(db_session, admin_user)
    policy = await db_session.get(ClientReportPolicy, client.id)
    db_session.add(DigestPeriodSkip(client_id=client.id, period_start=SEPT[0], period_end=SEPT[1],
                                    reason="Ya no se hace", skipped_by=admin_user.id))
    await db_session.flush()
    [item] = await preview_items(db_session, [(client, policy)])
    assert (item.state, item.reason, item.eligible) == ("skipped", "skipped", False)
    assert item.skip.reason == "Ya no se hace" and item.skip.skipped_by_name == admin_user.full_name

    # Si alguien lo entrega después, manda la entrega.
    digest = WeeklyDigest(client_id=client.id, period_start=SEPT[0], period_end=SEPT[1], created_by=admin_user.id,
                          created_at=NOW - timedelta(days=1))
    db_session.add(digest)
    await db_session.flush()
    db_session.add(DigestExternalDeliveryEvent(digest_id=digest.id, action=ExternalDeliveryAction.confirmed,
                                               actor_id=admin_user.id, request_key=uuid4().hex,
                                               request_hash="a" * 64, created_at=NOW))
    await db_session.flush()
    [item] = await preview_items(db_session, [(client, policy)])
    assert item.state == "externally_delivered" and item.skip is None
