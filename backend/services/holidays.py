"""Festivos de empresa: qué días libra cada persona.

Un festivo aplica a una persona si es nacional (sin región), de su comunidad
(su región sin municipio) o de su municipio (su región y su localidad). El
festivo local de otro municipio de la misma comunidad NO le aplica.

Sin persona (``user=None``) sólo cuentan los nacionales: es el calendario de
lo que es compartido por todo el equipo.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import CompanyHoliday, User

logger = logging.getLogger(__name__)


def _applies_condition(user: User | None):
    conditions = [CompanyHoliday.region.is_(None)]
    if user is not None and user.region:
        conditions.append((CompanyHoliday.region == user.region) & CompanyHoliday.locality.is_(None))
        if user.locality:
            conditions.append((CompanyHoliday.region == user.region) & (CompanyHoliday.locality == user.locality))
    return or_(*conditions)


def applies_to(holiday: CompanyHoliday, user: User | None) -> bool:
    """La misma regla que ``holidays_for``, para festivos ya cargados."""
    if holiday.region is None:
        return True
    if user is None or holiday.region != user.region:
        return False
    return holiday.locality is None or (bool(user.locality) and holiday.locality == user.locality)


async def holidays_for(db: AsyncSession, user: User | None, start: date, end: date) -> dict[date, CompanyHoliday]:
    """Festivos que libra ``user`` entre ``start`` y ``end`` (ambos incluidos)."""
    rows = (await db.scalars(select(CompanyHoliday).where(
        CompanyHoliday.date >= start,
        CompanyHoliday.date <= end,
        _applies_condition(user),
    ).order_by(CompanyHoliday.date, CompanyHoliday.id))).all()
    holidays: dict[date, CompanyHoliday] = {}
    for holiday in rows:
        holidays.setdefault(holiday.date, holiday)
    return holidays


@dataclass(frozen=True)
class HolidayCalendar:
    """Festivos de un tramo cargados de una vez, para repartirlos por persona
    sin una consulta por tarea (recurrencias en listas y en el generador)."""
    rows: tuple[CompanyHoliday, ...] = ()

    def for_user(self, user: User | None) -> frozenset[date]:
        return frozenset(holiday.date for holiday in self.rows if applies_to(holiday, user))


async def load_calendar(db: AsyncSession, start: date, end: date) -> HolidayCalendar:
    rows = (await db.scalars(select(CompanyHoliday).where(
        CompanyHoliday.date >= start, CompanyHoliday.date <= end,
    ).order_by(CompanyHoliday.date, CompanyHoliday.id))).all()
    return HolidayCalendar(tuple(rows))


async def is_working_day(db: AsyncSession, day: date, user: User | None) -> bool:
    """False en fin de semana y en los festivos que libra ``user``."""
    if day.weekday() >= 5:
        return False
    return not await holidays_for(db, user, day, day)


async def seed_national_holidays():
    """Seed Spanish national holidays for current and next year if not present."""
    from backend.db.database import async_session

    current_year = date.today().year

    # Festivos nacionales fijos de España (region=NULL = aplica a todos)
    NATIONAL_HOLIDAYS = [
        (1, 1, "Año Nuevo"),
        (1, 6, "Reyes Magos"),
        (5, 1, "Día del Trabajador"),
        (8, 15, "Asunción de la Virgen"),
        (10, 12, "Fiesta Nacional de España"),
        (11, 1, "Día de Todos los Santos"),
        (12, 6, "Día de la Constitución"),
        (12, 8, "Inmaculada Concepción"),
        (12, 25, "Navidad"),
    ]

    # Festivos móviles (Semana Santa). OJO: sólo 2026 y 2027; a partir de 2028
    # hay que añadirlos aquí o darlos de alta a mano en Ajustes → Festivos.
    MOVABLE_HOLIDAYS = {
        2026: [(4, 2, "Jueves Santo"), (4, 3, "Viernes Santo")],
        2027: [(3, 25, "Jueves Santo"), (3, 26, "Viernes Santo")],
    }

    async with async_session() as session:
        for year in [current_year, current_year + 1]:
            all_holidays = [(year, m, d, name) for m, d, name in NATIONAL_HOLIDAYS]
            for m, d, name in MOVABLE_HOLIDAYS.get(year, []):
                all_holidays.append((year, m, d, name))

            for y, m, d, name in all_holidays:
                try:
                    holiday_date = date(y, m, d)
                except ValueError:
                    continue
                existing = await session.execute(
                    select(CompanyHoliday).where(
                        CompanyHoliday.date == holiday_date,
                        CompanyHoliday.region.is_(None),
                    )
                )
                if existing.scalar_one_or_none() is None:
                    session.add(CompanyHoliday(
                        date=holiday_date, name=name, country="ES",
                        region=None, locality=None,
                    ))

        await session.commit()
    logging.info("National holidays seeded.")
