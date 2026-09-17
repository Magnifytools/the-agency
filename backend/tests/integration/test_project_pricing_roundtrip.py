"""Pricing fields survive manual and template project creation on PostgreSQL."""

from uuid import uuid4

import pytest

from backend.db.models import Client, ClientStatus


pytestmark = pytest.mark.integration


@pytest.fixture
async def pricing_client(db_session):
    client = Client(
        name=f"Pricing {uuid4().hex[:8]}",
        status=ClientStatus.active,
    )
    db_session.add(client)
    await db_session.flush()
    return client


async def test_manual_project_keeps_monthly_fee_and_total_budget_distinct(
    admin_client, pricing_client
):
    response = await admin_client.post("/api/projects", json={
        "name": "SEO anual",
        "client_id": pricing_client.id,
        "pricing_model": "monthly",
        "monthly_fee": 450,
        "budget_amount": 5400,
    })

    assert response.status_code == 201, response.text
    project = response.json()
    assert project["monthly_fee"] == 450
    assert project["budget_amount"] == 5400


async def test_template_creation_keeps_explicit_monthly_fee(
    admin_client, pricing_client
):
    key = f"pricing_{uuid4().hex}"
    created = await admin_client.post("/api/projects/templates", json={
        "key": key,
        "name": "Retainer mensual",
        "pricing_model": "monthly",
        "monthly_fee": 450,
    })
    assert created.status_code == 201, created.text

    response = await admin_client.post(
        "/api/projects/from-template",
        params={"client_id": pricing_client.id, "template_key": key},
    )

    assert response.status_code == 201, response.text
    project = response.json()
    assert project["pricing_model"] == "monthly"
    assert project["monthly_fee"] == 450
    assert project["budget_amount"] is None
