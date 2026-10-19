"""Festivos de empresa en el núcleo: CRUD de /api/holidays y a quién aplica cada uno."""
from datetime import date

from sqlalchemy import select

from backend.db.models import CompanyHoliday
from backend.services.holidays import applies_to, holidays_for, is_working_day

TUESDAY = date(2026, 9, 15)


async def test_admin_manages_holidays_and_member_only_reads(admin_client, member_client, db_session):
    created = await admin_client.post("/api/holidays", json={
        "date": "2026-09-15", "name": "Fiesta local", "region": "MAD", "locality": "Alcalá de Henares",
    })
    assert created.status_code == 201
    holiday = created.json()
    assert holiday | {"id": 0} == {"id": 0, "date": "2026-09-15", "name": "Fiesta local", "country": "ES",
                                   "region": "MAD", "locality": "Alcalá de Henares"}

    listed = await member_client.get("/api/holidays", params={"year": 2026})
    assert listed.status_code == 200
    assert [h["id"] for h in listed.json()] == [holiday["id"]]
    assert (await member_client.get("/api/holidays", params={"year": 2027})).json() == []

    assert (await member_client.post("/api/holidays", json={"date": "2026-09-16", "name": "x"})).status_code == 403
    assert (await member_client.delete(f"/api/holidays/{holiday['id']}")).status_code == 403

    assert (await admin_client.delete(f"/api/holidays/{holiday['id']}")).json() == {"ok": True}
    assert (await admin_client.delete(f"/api/holidays/{holiday['id']}")).status_code == 404
    assert await db_session.scalar(select(CompanyHoliday).where(CompanyHoliday.id == holiday["id"])) is None


async def test_old_my_week_holidays_route_is_gone(admin_client):
    assert (await admin_client.get("/api/my-week/holidays")).status_code in (404, 405, 422)


async def test_holiday_applies_by_region_and_locality(db_session, admin_user, member_user):
    admin_user.region, admin_user.locality = "MAD", "Madrid"
    member_user.region, member_user.locality = "MAD", "Alcalá de Henares"
    db_session.add_all([
        CompanyHoliday(date=TUESDAY, name="Local Alcalá", region="MAD", locality="Alcalá de Henares"),
        CompanyHoliday(date=date(2026, 9, 16), name="Comunidad", region="MAD"),
        CompanyHoliday(date=date(2026, 9, 17), name="Cataluña", region="CAT"),
    ])
    await db_session.flush()

    # El festivo local de Alcalá no es festivo para quien vive en Madrid capital.
    assert await is_working_day(db_session, TUESDAY, admin_user) is True
    assert await is_working_day(db_session, TUESDAY, member_user) is False
    # El de la comunidad, sí para los dos; el de otra comunidad, para ninguno.
    assert await is_working_day(db_session, date(2026, 9, 16), admin_user) is False
    assert await is_working_day(db_session, date(2026, 9, 17), member_user) is True
    # Sin persona sólo cuentan los nacionales.
    assert await is_working_day(db_session, date(2026, 9, 16), None) is True
    assert await is_working_day(db_session, date(2026, 9, 19), None) is False  # sábado

    member_days = await holidays_for(db_session, member_user, TUESDAY, date(2026, 9, 18))
    assert sorted(member_days) == [TUESDAY, date(2026, 9, 16)]
    for holiday in await db_session.scalars(select(CompanyHoliday)):
        expected = holiday.date in await holidays_for(db_session, admin_user, holiday.date, holiday.date)
        assert applies_to(holiday, admin_user) is expected
