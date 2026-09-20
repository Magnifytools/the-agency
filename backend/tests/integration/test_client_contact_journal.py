"""Client/contact writers and grouped Undo use real PostgreSQL constraints."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import (
    ChangeLog,
    Client,
    ClientContact,
    ClientResource,
    Project,
    User,
    UserRole,
)
from backend.services import change_journal as journal
from backend.services.domain_writes import create_client, create_contact, create_project

pytestmark = pytest.mark.asyncio


async def _grouped_creation(db, actor_id: int):
    before = set((await db.scalars(select(ChangeLog.id))).all())
    journal.set_actor(actor_id)
    try:
        client = await create_client(db, {"name": f"Onboarding {uuid4()}"})
        contact = await create_contact(db, client.id, {
            "name": "Contacto principal", "is_primary": True,
        })
        project = await create_project(db, {
            "name": "Proyecto inicial", "client_id": client.id,
        })
        await db.commit()
    finally:
        journal.set_actor(None)
    change = await db.scalar(
        select(ChangeLog).where(ChangeLog.id.notin_(before)).order_by(ChangeLog.id.desc())
    )
    assert change is not None
    return client.id, contact.id, project.id, change


async def test_grouped_client_contact_project_undo_removes_fk_children_first(
    admin_client, admin_user, db_session,
):
    client_id, contact_id, project_id, change = await _grouped_creation(db_session, admin_user.id)
    assert {op["entity_type"] for op in change.operations} == {
        "client", "client_contact", "project",
    }

    response = await admin_client.post(f"/api/changes/{change.id}/undo")
    assert response.status_code == 200, response.text
    db_session.expire_all()
    assert await db_session.get(ClientContact, contact_id) is None
    assert await db_session.get(Project, project_id) is None
    assert await db_session.get(Client, client_id) is None


async def test_grouped_undo_refuses_a_reference_added_after_onboarding(
    admin_client, admin_user, db_session,
):
    client_id, contact_id, project_id, change = await _grouped_creation(db_session, admin_user.id)
    db_session.add(ClientResource(
        client_id=client_id, label="Trabajo posterior", url="https://example.test/resource",
    ))
    await db_session.commit()

    response = await admin_client.post(f"/api/changes/{change.id}/undo")
    assert response.status_code == 409, response.text
    db_session.expire_all()
    assert await db_session.get(Client, client_id) is not None
    assert await db_session.get(ClientContact, contact_id) is not None
    assert await db_session.get(Project, project_id) is not None
    await db_session.refresh(change)
    assert change.undone_at is None


async def test_grouped_undo_checks_current_module_permissions(
    member_client, member_user, db_session,
):
    client_id, contact_id, project_id, change = await _grouped_creation(db_session, member_user.id)

    response = await member_client.post(f"/api/changes/{change.id}/undo")
    assert response.status_code == 403, response.text
    assert await db_session.get(Client, client_id) is not None
    assert await db_session.get(ClientContact, contact_id) is not None
    assert await db_session.get(Project, project_id) is not None


async def test_contact_crud_is_journaled_and_create_can_be_undone(
    admin_client, admin_user, db_session,
):
    client = Client(name=f"Contact journal {uuid4()}")
    db_session.add(client)
    await db_session.commit()
    before = set((await db_session.scalars(select(ChangeLog.id))).all())

    created = await admin_client.post(f"/api/clients/{client.id}/contacts", json={
        "name": "Contacto journal", "is_primary": True,
    })
    assert created.status_code == 201, created.text
    contact_id = created.json()["id"]
    change = await db_session.scalar(
        select(ChangeLog).where(ChangeLog.id.notin_(before)).order_by(ChangeLog.id.desc())
    )
    assert change is not None
    assert change.entity_type == "client_contact"
    assert change.operations[0]["entity_type"] == "client_contact"

    undone = await admin_client.post(f"/api/changes/{change.id}/undo")
    assert undone.status_code == 200, undone.text
    assert await db_session.get(ClientContact, contact_id) is None


async def test_contact_update_and_delete_are_each_undoable(
    admin_client, db_session,
):
    client = Client(name=f"Contact mutations {uuid4()}")
    contact = ClientContact(client=client, name="Nombre original", is_primary=False)
    db_session.add_all([client, contact])
    await db_session.commit()
    client_id, contact_id = client.id, contact.id
    seen = set((await db_session.scalars(select(ChangeLog.id))).all())

    updated = await admin_client.put(
        f"/api/clients/{client_id}/contacts/{contact_id}", json={"name": "Nombre nuevo"},
    )
    assert updated.status_code == 200, updated.text
    update_change = await db_session.scalar(
        select(ChangeLog).where(ChangeLog.id.notin_(seen)).order_by(ChangeLog.id.desc())
    )
    assert update_change is not None
    assert update_change.operations[0]["action"] == "update"
    update_change_id = update_change.id
    assert (await admin_client.post(f"/api/changes/{update_change_id}/undo")).status_code == 200
    db_session.expire_all()
    assert (await db_session.get(ClientContact, contact_id)).name == "Nombre original"
    seen.add(update_change_id)

    deleted = await admin_client.delete(f"/api/clients/{client_id}/contacts/{contact_id}")
    assert deleted.status_code == 204, deleted.text
    delete_change = await db_session.scalar(
        select(ChangeLog).where(ChangeLog.id.notin_(seen)).order_by(ChangeLog.id.desc())
    )
    assert delete_change is not None
    assert delete_change.operations[0]["action"] == "delete"
    assert (await admin_client.post(f"/api/changes/{delete_change.id}/undo")).status_code == 200
    db_session.expire_all()
    assert (await db_session.get(ClientContact, contact_id)).name == "Nombre original"


async def test_concurrent_primary_writers_serialize_on_client(engine):
    async with AsyncSession(engine, expire_on_commit=False) as setup:
        client = Client(name=f"Primary lock {uuid4()}")
        setup.add(client)
        await setup.commit()
        client_id = client.id

    first_flushed = asyncio.Event()
    release_first = asyncio.Event()

    async def writer(name: str, pause: bool):
        async with AsyncSession(engine, expire_on_commit=False) as session:
            contact = await create_contact(session, client_id, {"name": name, "is_primary": True})
            if pause:
                first_flushed.set()
                await release_first.wait()
            await session.commit()
            return contact.id

    first = asyncio.create_task(writer("Primero", True))
    await first_flushed.wait()
    second = asyncio.create_task(writer("Segundo", False))
    await asyncio.sleep(0)
    assert not second.done()
    release_first.set()
    await asyncio.gather(first, second)

    async with AsyncSession(engine) as verify:
        primary_count = await verify.scalar(select(func.count(ClientContact.id)).where(
            ClientContact.client_id == client_id,
            ClientContact.is_primary.is_(True),
        ))
        primary_name = await verify.scalar(select(ClientContact.name).where(
            ClientContact.client_id == client_id,
            ClientContact.is_primary.is_(True),
        ))
        assert primary_count == 1
        assert primary_name == "Segundo"


async def test_undo_deleted_primary_refuses_to_replace_later_primary(
    admin_client, admin_user, db_session,
):
    client = Client(name=f"Primary undo conflict {uuid4()}")
    primary = ClientContact(client=client, name="Principal A", is_primary=True)
    db_session.add_all([client, primary])
    await db_session.commit()
    client_id, primary_id = client.id, primary.id
    seen = set((await db_session.scalars(select(ChangeLog.id))).all())

    deleted = await admin_client.delete(f"/api/clients/{client_id}/contacts/{primary_id}")
    assert deleted.status_code == 204, deleted.text
    delete_change = await db_session.scalar(
        select(ChangeLog).where(ChangeLog.id.notin_(seen)).order_by(ChangeLog.id.desc())
    )
    assert delete_change is not None
    replacement = await admin_client.post(f"/api/clients/{client_id}/contacts", json={
        "name": "Principal B", "is_primary": True,
    })
    assert replacement.status_code == 201, replacement.text

    undone = await admin_client.post(f"/api/changes/{delete_change.id}/undo")
    assert undone.status_code == 409, undone.text
    assert "otro contacto principal" in undone.json()["detail"]
    db_session.expire_all()
    assert await db_session.get(ClientContact, primary_id) is None
    replacement_row = await db_session.get(ClientContact, replacement.json()["id"])
    assert replacement_row is not None and replacement_row.is_primary is True
    await db_session.refresh(delete_change)
    assert delete_change.undone_at is None


async def test_undo_contact_and_primary_writer_serialize_on_client(engine, monkeypatch):
    from backend.api.routes import changes as changes_route
    from backend.core.security import hash_password

    async with AsyncSession(engine, expire_on_commit=False) as setup:
        actor_row = User(
            email=f"contact-undo-{uuid4()}@test.local",
            full_name="Contact Undo",
            hashed_password=hash_password("unused"),
            role=UserRole.admin,
            is_active=True,
        )
        client = Client(name=f"Primary undo lock {uuid4()}")
        primary = ClientContact(client=client, name="Principal borrado", is_primary=True)
        setup.add_all([actor_row, client, primary])
        await setup.commit()
        actor_id, client_id = actor_row.id, client.id
        journal.set_actor(actor_id)
        try:
            await setup.delete(primary)
            await setup.commit()
        finally:
            journal.set_actor(None)
        change = await setup.scalar(select(ChangeLog).where(
            ChangeLog.user_id == actor_id,
            ChangeLog.entity_type == "client_contact",
            ChangeLog.action == "delete",
        ).order_by(ChangeLog.id.desc()))
        assert change is not None
        change_id = change.id

    parent_locked = asyncio.Event()
    release_undo = asyncio.Event()
    original_preflight = changes_route._preflight_contact_primaries

    async def paused_preflight(*args, **kwargs):
        parent_locked.set()
        await release_undo.wait()
        return await original_preflight(*args, **kwargs)

    monkeypatch.setattr(changes_route, "_preflight_contact_primaries", paused_preflight)
    actor = SimpleNamespace(id=actor_id, role=UserRole.admin, permissions=[])
    async with AsyncSession(engine, expire_on_commit=False) as undo_db, AsyncSession(engine) as writer_db:
        undo_task = asyncio.create_task(changes_route.undo_change(
            change_id, db=undo_db, current_user=actor,
        ))
        await asyncio.wait_for(parent_locked.wait(), timeout=2)

        async def write_replacement():
            await create_contact(writer_db, client_id, {
                "name": "Principal concurrente", "is_primary": True,
            })
            await writer_db.commit()

        writer_task = asyncio.create_task(write_replacement())
        await asyncio.sleep(0.1)
        assert not writer_task.done(), "el escritor no esperó el bloqueo del cliente de Undo"
        release_undo.set()
        await asyncio.wait_for(undo_task, timeout=2)
        await asyncio.wait_for(writer_task, timeout=2)

    async with AsyncSession(engine) as verify:
        primaries = (await verify.scalars(
            select(ClientContact).where(
                ClientContact.client_id == client_id,
                ClientContact.is_primary.is_(True),
            )
        )).all()
        assert [contact.name for contact in primaries] == ["Principal concurrente"]
