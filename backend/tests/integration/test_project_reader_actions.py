"""A project reader can list projects but cannot create or delete them."""

from backend.db.models import Client, Project


async def test_project_reader_cannot_create_or_delete(db_session, make_member_client):
    client = Client(name="Project reader guard")
    db_session.add(client)
    await db_session.flush()
    project = Project(name="Existing project", client_id=client.id)
    db_session.add(project)
    await db_session.commit()

    reader = await make_member_client([("projects", True, False)])
    listing = await reader.get("/api/projects", params={"client_id": client.id})
    assert listing.status_code == 200, listing.text
    assert any(item["id"] == project.id for item in listing.json()["items"])

    created = await reader.post("/api/projects", json={"name": "Forbidden project", "client_id": client.id})
    assert created.status_code == 403
    deleted = await reader.delete(f"/api/projects/{project.id}")
    assert deleted.status_code == 403

    after = await reader.get("/api/projects", params={"client_id": client.id})
    assert [item["id"] for item in after.json()["items"]] == [project.id]
