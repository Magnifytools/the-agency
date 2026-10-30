"""Peticiones fuera de alcance: reglas puras, permisos y contrato de la migración."""
from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from backend.db.models import ClientScopeRequest
from backend.services import scope_requests as service
from backend.startup import deployment_schema
from backend.startup.client_scope_requests_schema import CONTRACT, MIGRATION


def _row(requested_on, minutes, decision):
    return SimpleNamespace(requested_on=requested_on, estimated_minutes=minutes, decision=decision)


def test_los_totales_del_mes_suman_por_decision_y_solo_el_mes():
    rows = [
        _row(date(2026, 10, 1), 30, "absorb"),
        _row(date(2026, 10, 31), 45, "absorb"),
        _row(date(2026, 10, 15), 120, "bill"),
        _row(date(2026, 10, 2), 60, "pending"),
        _row(date(2026, 10, 3), 15, "swap"),
        # Pendiente de septiembre: se enseña en la lista, pero no suma en octubre.
        _row(date(2026, 9, 30), 500, "pending"),
        _row(date(2026, 11, 1), 500, "bill"),
    ]
    start, end, key = service.month_range("2026-10")
    assert (start, end, key) == (date(2026, 10, 1), date(2026, 11, 1), "2026-10")
    assert service.month_totals(rows, start, end) == {
        "absorbed_minutes": 75, "billable_minutes": 120, "swapped_minutes": 15,
        "pending_minutes": 60, "count": 5,
    }


def test_mes_actual_por_defecto_y_formato_estricto():
    assert service.month_range(None, today=date(2026, 12, 9))[:2] == (date(2026, 12, 1), date(2027, 1, 1))
    for bad in ("2026-13", "2026/10", "26-10", "2026-1"):
        with pytest.raises(ValueError):
            service.month_range(bad)


def test_decidir_apunta_quien_y_cuando_y_pendiente_lo_borra():
    actor = SimpleNamespace(id=7)
    row = ClientScopeRequest(decision="pending")
    service.apply_decision(row, "bill", actor)
    assert row.decision == "bill" and row.decided_by == 7 and row.decided_at is not None
    first = row.decided_at
    # Repetir la misma decisión no reescribe quién ni cuándo.
    service.apply_decision(row, "bill", SimpleNamespace(id=9))
    assert row.decided_by == 7 and row.decided_at == first
    service.apply_decision(row, "pending", actor)
    assert row.decided_by is None and row.decided_at is None


def test_la_migracion_esta_en_el_plan_y_casa_con_el_orm():
    assert MIGRATION in deployment_schema.MIGRATIONS
    columns = CONTRACT["columns"]["client_scope_requests"]
    assert set(columns) == {c.name for c in ClientScopeRequest.__table__.columns}
    checks = {c.name for c in ClientScopeRequest.__table__.constraints if c.name and c.name.startswith("ck_")}
    assert checks == set(CONTRACT["check_constraints"]["client_scope_requests"])


def test_entra_en_el_deshacer_con_permiso_de_clientes():
    from backend.services import change_journal as cj
    spec = cj._SPECS[ClientScopeRequest]
    assert spec.module == "clients" and spec.rank == 1


@pytest.mark.asyncio
class TestPermisos:
    async def test_sin_escritura_de_clientes_no_se_apunta(self, member_client):
        resp = await member_client.post("/api/clients/1/scope-requests", json={
            "title": "Revisar landing de Navidad", "estimated_minutes": 60,
        })
        assert resp.status_code == 403

    async def test_sin_escritura_de_clientes_no_se_decide_ni_se_borra(self, member_client):
        assert (await member_client.patch("/api/clients/1/scope-requests/1", json={"decision": "bill"})).status_code == 403
        assert (await member_client.delete("/api/clients/1/scope-requests/1")).status_code == 403

    async def test_desde_por_aclarar_pide_escritura_de_clientes(self, member_client):
        resp = await member_client.post("/api/inbox/1/scope-request", json={"client_id": 1, "estimated_minutes": 30})
        assert resp.status_code == 403

    async def test_validacion(self, admin_client):
        base = "/api/clients/1/scope-requests"
        assert (await admin_client.post(base, json={"title": "   ", "estimated_minutes": 10})).status_code == 422
        assert (await admin_client.post(base, json={"title": "X", "estimated_minutes": 0})).status_code == 422
        assert (await admin_client.post(base, json={"title": "X", "estimated_minutes": 60001})).status_code == 422
        assert (await admin_client.post(base, json={"title": "X", "estimated_minutes": 5, "decision": "gratis"})).status_code == 422

