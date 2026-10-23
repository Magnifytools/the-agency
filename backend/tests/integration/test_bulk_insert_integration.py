"""Inserciones grandes contra Postgres real: ningún INSERT pasa de 32.767 parámetros.

asyncpg lo rechaza ("the number of query arguments cannot exceed 32767"), y
SQLAlchemy cuenta también las columnas con default de Python que la fila no
trae. Con lotes fijos de 5.000, `gsc_query_monthly` (7 columnas) reventaba en
producción con Sage. Se prueba con más filas de las que caben en un INSERT.
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import func, select

from backend.db.bulk import POSTGRES_MAX_PARAMS, insert_chunks
from backend.db.models import Ga4LeadDaily, GscQueryDaily, GscQueryMonthly
from backend.services import ga4_leads
from backend.services import gsc_detail_service as detail
from backend.services.ga4_leads import LeadRow
from backend.services.gsc_detail_service import DetailRow, MonthRow

pytestmark = pytest.mark.integration

SITE = "sc-domain:ejemplo.com"
MONTH = date(2026, 9, 1)
DAY = date(2026, 10, 1)


def _over_one_insert(model) -> int:
    return POSTGRES_MAX_PARAMS // len(model.__table__.columns) * 2 + 1


async def _count(db, model):
    return await db.scalar(select(func.count()).select_from(model))


def test_ningun_trozo_pasa_del_limite_de_parametros():
    for model in (GscQueryMonthly, GscQueryDaily, Ga4LeadDaily):
        columns = len(model.__table__.columns)
        values = list(range(_over_one_insert(model)))
        chunks = list(insert_chunks(model, values))
        assert sum(len(c) for c in chunks) == len(values)
        assert all(len(c) * columns <= POSTGRES_MAX_PARAMS for c in chunks)


async def test_un_mes_con_muchas_consultas_se_guarda_entero(db_session):
    n = _over_one_insert(GscQueryMonthly)
    rows = [MonthRow(query=f"consulta {i}", clicks=1, impressions=10, position=3.0) for i in range(n)]

    await detail._replace_month(db_session, SITE, MONTH, rows)

    assert await _count(db_session, GscQueryMonthly) == n


async def test_un_tramo_diario_con_muchas_consultas_se_guarda_entero(db_session):
    n = _over_one_insert(GscQueryDaily)
    rows = [DetailRow(date=DAY, key=f"consulta {i}", clicks=1, impressions=10, position=3.0) for i in range(n)]

    await detail._replace(db_session, "query", SITE, DAY, DAY, rows)

    assert await _count(db_session, GscQueryDaily) == n


async def test_muchos_leads_se_guardan_enteros(db_session):
    n = _over_one_insert(Ga4LeadDaily)
    rows = [LeadRow(date=DAY, landing_page=f"ejemplo.com/p/{i}", channel="Organic Search", leads=1)
            for i in range(n)]

    assert await ga4_leads.replace_range(db_session, "123", DAY, DAY, rows) == n
    assert await _count(db_session, Ga4LeadDaily) == n
