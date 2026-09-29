"""Lifecycle list filters apply before totals, global ordering and pagination."""
from datetime import datetime, timedelta

from backend.db.models import Client, Project, ProjectStatus


async def test_archive_and_portfolio_paginate_the_complete_filtered_population(
    admin_client, db_session,
):
    client = Client(name="Archive list")
    db_session.add(client)
    await db_session.flush()
    statuses = [ProjectStatus.active, ProjectStatus.completed, ProjectStatus.planning,
                ProjectStatus.cancelled, ProjectStatus.on_hold, ProjectStatus.completed]
    rows = []
    for index, status in enumerate(statuses):
        project = Project(
            name=f"List {index}", client_id=client.id, status=status,
            created_at=datetime(2026, 9, 1) + timedelta(days=index),
            is_recurring=index % 2 == 1,
        )
        db_session.add(project)
        rows.append(project)
    await db_session.commit()
    params = {"client_id": client.id, "page_size": 2}
    for lifecycle, indices in [("portfolio", [4, 2, 0]), ("archive", [5, 3, 1])]:
        found = []
        for page in [1, 2]:
            response = await admin_client.get("/api/projects", params={
                **params, "lifecycle": lifecycle, "page": page,
            })
            assert response.status_code == 200, response.text
            payload = response.json()
            assert payload["total"] == 3
            found.extend(row["id"] for row in payload["items"])
        assert found == [rows[index].id for index in indices]
    all_rows = await admin_client.get("/api/projects", params={**params, "page_size": 25})
    assert all_rows.json()["total"] == 6
    filtered = await admin_client.get("/api/projects", params={
        **params, "lifecycle": "archive", "status": "completed", "is_recurring": True,
    })
    assert filtered.json()["total"] == 2
    assert [row["id"] for row in filtered.json()["items"]] == [rows[5].id, rows[1].id]
    incompatible = await admin_client.get("/api/projects", params={
        **params, "lifecycle": "portfolio", "status": "completed",
    })
    assert incompatible.json()["total"] == 0
    invalid = await admin_client.get("/api/projects", params={"lifecycle": "anything"})
    assert invalid.status_code == 422


async def test_owner_filter_uses_the_full_lifecycle_cohort_before_pagination(
    admin_client, member_client, db_session,
):
    client = Client(name="Ownership list")
    db_session.add(client)
    await db_session.flush()
    rows = []
    for index, (status, owner_id) in enumerate([
        (ProjectStatus.active, None),
        (ProjectStatus.active, admin_client.test_user.id),
        (ProjectStatus.planning, None),
        (ProjectStatus.completed, None),
    ]):
        project = Project(
            name=f"Ownership {index}", client_id=client.id,
            status=status, owner_id=owner_id,
            created_at=datetime(2026, 9, 1) + timedelta(days=index),  # noqa: DTZ001 - legacy naive DB timestamp
        )
        db_session.add(project)
        rows.append(project)
    await db_session.commit()

    unassigned = await admin_client.get("/api/projects", params={
        "client_id": client.id, "lifecycle": "portfolio", "owner": "unassigned",
        "page_size": 1,
    })
    assert unassigned.status_code == 200, unassigned.text
    assert unassigned.json()["total"] == 2
    assert [item["id"] for item in unassigned.json()["items"]] == [rows[2].id]
    second = await admin_client.get("/api/projects", params={
        "client_id": client.id, "lifecycle": "portfolio", "owner": "unassigned",
        "page_size": 1, "page": 2,
    })
    assert second.json()["total"] == 2
    assert [item["id"] for item in second.json()["items"]] == [rows[0].id]

    assigned = await admin_client.get("/api/projects", params={
        "client_id": client.id, "lifecycle": "portfolio", "owner": "assigned",
    })
    assert [item["id"] for item in assigned.json()["items"]] == [rows[1].id]
    archived = await admin_client.get("/api/projects", params={
        "client_id": client.id, "lifecycle": "archive", "owner": "unassigned",
    })
    assert [item["id"] for item in archived.json()["items"]] == [rows[3].id]
    active = await admin_client.get("/api/projects", params={
        "client_id": client.id, "status": "active", "owner": "unassigned",
    })
    assert [item["id"] for item in active.json()["items"]] == [rows[0].id]
    denied_member = await member_client.get("/api/projects", params={
        "client_id": client.id, "lifecycle": "portfolio", "owner": "unassigned",
    })
    assert denied_member.status_code == 403
    invalid = await admin_client.get("/api/projects", params={"owner": "anyone"})
    assert invalid.status_code == 422
