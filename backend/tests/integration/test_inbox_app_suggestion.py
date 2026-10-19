"""Una nota del inbox enviada como sugerencia para la app llega a los admins."""
from __future__ import annotations

import pytest
from sqlalchemy import select

from backend.db.models import InboxNote, Notification


@pytest.mark.asyncio
async def test_member_suggestion_notifies_admins_once_and_resolves_the_note(
    admin_client, make_member_client, db_session,
):
    member = await make_member_client([("tasks", True, True)])
    note = InboxNote(user_id=member.test_user.id, raw_text="Que Hoy enseñe los seguimientos", source="dashboard")
    db_session.add(note)
    await db_session.flush()

    first = await member.post(f"/api/inbox/{note.id}/suggest")
    again = await member.post(f"/api/inbox/{note.id}/suggest")
    assert first.status_code == 200, first.text
    assert first.json()["status"] == "processed" and first.json()["resolved_as"] == "app_suggestion"
    assert again.status_code == 200

    sent = (await db_session.scalars(select(Notification).where(Notification.type == "app_suggestion"))).all()
    assert [(n.user_id, n.message) for n in sent] == [(admin_client.test_user.id, "Que Hoy enseñe los seguimientos")]

    blocked = await member.post(f"/api/inbox/{note.id}/convert-to-task", json={})
    assert blocked.status_code == 409 and "sugerencia" in blocked.json()["detail"]


@pytest.mark.asyncio
async def test_only_the_author_can_send_their_note(admin_client, make_member_client, db_session):
    member = await make_member_client([])
    note = InboxNote(user_id=admin_client.test_user.id, raw_text="Privada", source="dashboard")
    db_session.add(note)
    await db_session.flush()

    assert (await member.post(f"/api/inbox/{note.id}/suggest")).status_code == 404
    own = await admin_client.post(f"/api/inbox/{note.id}/suggest")
    assert own.status_code == 200
    # Quien la envía no se avisa a sí mismo.
    assert (await db_session.scalars(select(Notification).where(Notification.type == "app_suggestion"))).all() == []
