"""El informe SEO local entregado cuenta como informe mensual del cliente.

Lo miran el aviso de mensual sin entregar, el de pendiente, "Para entregar" y el
estado del cliente. El informe es del mes en que EMPIEZA (octubre de 2026 iba
del 1 al 26).
"""
from datetime import date, datetime, timedelta
from uuid import uuid4

from sqlalchemy import select

from backend.db.models import (
    Client,
    ClientLocalReport,
    ClientLocalReportConfig,
    ClientReportPolicy,
    ClientStatus,
    Notification,
    User,
    UserPermission,
    UserRole,
)
from backend.services import client_status
from backend.services.digest_periods import policy_digest_period
from backend.services.incident_report_conditions import collect_report_conditions, report_visibility_clause
from backend.services.incidents import reconcile_recipient
from backend.services.report_policy import preview_items

NOW = datetime(2026, 11, 2, 8)  # noqa: DTZ001 - first business day of November
OCT = (date(2026, 10, 1), date(2026, 10, 26))


async def _member(db):
    user = User(email=f"local-{uuid4().hex}@test.local", full_name="Responsable", hashed_password="x",
                role=UserRole.member, is_active=True)
    db.add(user)
    await db.flush()
    db.add(UserPermission(user_id=user.id, module="digests", can_read=True, can_write=True))
    await db.flush()
    return user


async def _client(db, responsible, *, config=True):
    client = Client(name=f"Cliente {uuid4().hex[:8]}", status=ClientStatus.active, is_internal=False)
    db.add(client)
    await db.flush()
    db.add(ClientReportPolicy(client_id=client.id, monthly_enabled=True, responsible_user_id=responsible.id))
    if config:
        db.add(ClientLocalReportConfig(client_id=client.id, template="cigarral", landing_url="https://example.com/",
                                       settings={}, roadmap={}))
    await db.flush()
    return client


async def _report(db, client, period=OCT, *, delivered_by=None):
    at = NOW - timedelta(days=3)
    report = ClientLocalReport(client_id=client.id, period_start=period[0], period_end=period[1], datos={}, roadmap={},
                               generated_at=at if delivered_by else None,
                               html=b"x" if delivered_by else None, pdf=b"x" if delivered_by else None,
                               delivered_at=at if delivered_by else None,
                               delivered_by=delivered_by.id if delivered_by else None)
    db.add(report)
    await db.flush()
    return report


async def _kinds(db, user_id, client_id, now=NOW):
    return {c.kind: c for c in (await collect_report_conditions(db, user_id, now)).values() if c.entity_id == client_id}


async def test_sin_version_pide_el_informe_seo_local_en_su_pestana(db_session, admin_user):
    owner = await _member(db_session)
    client = await _client(db_session, owner)

    pending = (await _kinds(db_session, owner.id, client.id))["report_pending"]
    assert pending.message == "Falta preparar el informe SEO local del 01/10/2026 al 31/10/2026."
    assert pending.href == f"/clients/{client.id}?tab=informe_local"
    unsent = (await _kinds(db_session, admin_user.id, client.id))["report_unsent"]
    assert unsent.message == "Falta preparar y entregar el informe SEO local de octubre de 2026."
    assert unsent.href == f"/clients/{client.id}?tab=informe_local"


async def test_version_sin_entregar_y_entregada(db_session, admin_user):
    owner = await _member(db_session)
    client = await _client(db_session, owner)
    draft = await _report(db_session, client)

    # Preparado: ya no es "pendiente", pero sigue sin entregar.
    assert set(await _kinds(db_session, owner.id, client.id)) == {"report_unsent"}
    unsent = (await _kinds(db_session, admin_user.id, client.id))["report_unsent"]
    assert f"versión #{draft.id}" in unsent.message
    assert unsent.href == f"/clients/{client.id}?tab=informe_local"

    await reconcile_recipient(db_session, admin_user.id, now=NOW)
    incident = (await db_session.execute(select(Notification).where(
        Notification.user_id == admin_user.id, Notification.type == "report_unsent",
        Notification.entity_id == client.id,
    ))).scalar_one()
    current = report_visibility_clause(admin_user.id, current_only=True, now=NOW)
    assert await db_session.scalar(select(Notification.id).where(Notification.id == incident.id, current)) == incident.id

    await _report(db_session, client, delivered_by=owner)
    assert await _kinds(db_session, admin_user.id, client.id) == {}
    assert await _kinds(db_session, owner.id, client.id) == {}
    assert await db_session.scalar(select(Notification.id).where(Notification.id == incident.id, current)) is None


async def test_un_informe_de_otro_mes_no_cuenta(db_session, admin_user):
    owner = await _member(db_session)
    client = await _client(db_session, owner)
    await _report(db_session, client, (date(2026, 9, 1), date(2026, 9, 30)), delivered_by=owner)
    await _report(db_session, client, (date(2026, 11, 1), date(2026, 11, 1)), delivered_by=owner)
    assert set(await _kinds(db_session, admin_user.id, client.id)) == {"report_unsent"}


async def test_estado_del_cliente_cuenta_el_mes_entero(db_session):
    owner = await _member(db_session)
    client = await _client(db_session, owner)
    await _report(db_session, client, delivered_by=owner)
    policies, last_sent = await client_status._digests(db_session, [client.id])
    assert last_sent[(client.id, "monthly")] == date(2026, 10, 31)
    [signal] = client_status._digest_signals(policies[client.id], last_sent, NOW.date())
    assert signal["state"] == "ok"


async def test_para_entregar_lee_el_informe_seo_local(db_session):
    owner = await _member(db_session)
    local = await _client(db_session, owner)
    plain = await _client(db_session, owner, config=False)
    month = policy_digest_period("monthly")
    policies = {p.client_id: p for p in (await db_session.scalars(select(ClientReportPolicy).where(
        ClientReportPolicy.client_id.in_([local.id, plain.id]))))}

    items = {i.client_id: i for i in await preview_items(db_session, [(local, policies[local.id]), (plain, policies[plain.id])])}
    assert items[local.id].reason == "local_report" and not items[local.id].eligible
    assert items[local.id].state == "local_missing"
    assert items[local.id].local_report.report_id is None
    assert items[plain.id].local_report is None and items[plain.id].eligible

    draft = await _report(db_session, local, (month[0], month[0] + timedelta(days=20)))
    [item] = [i for i in await preview_items(db_session, [(local, policies[local.id])])]
    assert item.state == "local_prepared" and item.local_report.report_id == draft.id

    delivered = await _report(db_session, local, (month[0], month[0] + timedelta(days=25)), delivered_by=owner)
    [item] = [i for i in await preview_items(db_session, [(local, policies[local.id])])]
    assert item.state == "local_delivered"
    assert item.local_report.report_id == delivered.id
    assert item.local_report.delivered_by_name == "Responsable"
