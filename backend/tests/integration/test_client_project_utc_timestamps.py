"""Client onboarding timestamps remain naive UTC in non-UTC DB sessions."""
from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select, text

from backend.db.models import Client, ClientContact, Project


pytestmark = pytest.mark.integration


async def _db_utc_now(db):
    return await db.scalar(text("SELECT timezone('UTC', clock_timestamp())"))


async def test_client_project_and_contact_insert_and_update_use_utc_clock(db_session):
    await db_session.execute(text("SET LOCAL TIME ZONE 'Europe/Madrid'"))
    before_insert = await _db_utc_now(db_session)
    client = Client(name="UTC client")
    db_session.add(client)
    await db_session.flush()
    project = Project(name="UTC project", client_id=client.id)
    contact = ClientContact(name="UTC contact", client_id=client.id)
    db_session.add_all([project, contact])
    await db_session.flush()
    after_insert = await _db_utc_now(db_session)

    for row in (client, project, contact):
        assert before_insert - timedelta(seconds=3) <= row.created_at <= after_insert + timedelta(seconds=3)
        assert before_insert - timedelta(seconds=3) <= row.updated_at <= after_insert + timedelta(seconds=3)

    before_update = await _db_utc_now(db_session)
    client.name = "UTC client updated"
    project.name = "UTC project updated"
    contact.name = "UTC contact updated"
    await db_session.flush()
    after_update = await _db_utc_now(db_session)

    for row in (client, project, contact):
        await db_session.refresh(row, attribute_names=["updated_at"])
        assert before_update - timedelta(seconds=3) <= row.updated_at <= after_update + timedelta(seconds=3)

    stored = (await db_session.execute(select(
        Client.created_at, Project.created_at, ClientContact.created_at,
    ).join(Project, Project.client_id == Client.id).join(
        ClientContact, ClientContact.client_id == Client.id,
    ).where(Client.id == client.id))).one()
    assert stored == (client.created_at, project.created_at, contact.created_at)
