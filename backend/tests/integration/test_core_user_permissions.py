"""The active Users screen can manage permissions without enabling Invitations."""

from sqlalchemy import select

from backend.db.models import UserPermission


async def _stored_permissions(db_session, user_id: int):
    rows = (await db_session.execute(
        select(
            UserPermission.module,
            UserPermission.can_read,
            UserPermission.can_write,
        )
        .where(UserPermission.user_id == user_id)
        .order_by(UserPermission.module, UserPermission.id)
    )).all()
    return [(row.module, row.can_read, row.can_write) for row in rows]


async def test_admin_reads_and_replaces_member_permissions_from_core_users_api(
    admin_client, member_user, db_session,
):
    db_session.add(UserPermission(
        user_id=member_user.id,
        module="tasks",
        can_read=True,
        can_write=False,
    ))
    await db_session.flush()

    response = await admin_client.get(f"/api/users/{member_user.id}/permissions")
    assert response.status_code == 200
    assert response.json() == [
        {"module": "tasks", "can_read": True, "can_write": False},
    ]

    response = await admin_client.put(
        f"/api/users/{member_user.id}/permissions",
        json={"permissions": [
            {"module": "projects", "can_read": True, "can_write": False},
            {"module": "timesheet", "can_read": True, "can_write": True},
        ]},
    )
    assert response.status_code == 200
    assert response.json() == [
        {"module": "projects", "can_read": True, "can_write": False},
        {"module": "timesheet", "can_read": True, "can_write": True},
    ]
    assert await _stored_permissions(db_session, member_user.id) == [
        ("projects", True, False),
        ("timesheet", True, True),
    ]


async def test_member_cannot_read_or_replace_permissions(member_client, member_user):
    read = await member_client.get(f"/api/users/{member_user.id}/permissions")
    write = await member_client.put(
        f"/api/users/{member_user.id}/permissions",
        json={"permissions": []},
    )
    assert read.status_code == 403
    assert write.status_code == 403


async def test_admin_target_cannot_be_modified(admin_client, admin_user):
    response = await admin_client.put(
        f"/api/users/{admin_user.id}/permissions",
        json={"permissions": [{"module": "tasks", "can_read": True, "can_write": True}]},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "Cannot modify admin permissions"


async def test_invalid_or_duplicate_modules_do_not_erase_existing_permissions(
    admin_client, member_user, db_session,
):
    db_session.add(UserPermission(
        user_id=member_user.id,
        module="tasks",
        can_read=True,
        can_write=False,
    ))
    await db_session.flush()

    for permissions, expected_detail in [
        (
            [{"module": "not-a-module", "can_read": True, "can_write": True}],
            "Módulos no reconocidos",
        ),
        (
            [
                {"module": "projects", "can_read": True, "can_write": False},
                {"module": "projects", "can_read": False, "can_write": False},
            ],
            "Módulos duplicados",
        ),
    ]:
        response = await admin_client.put(
            f"/api/users/{member_user.id}/permissions",
            json={"permissions": permissions},
        )
        assert response.status_code == 422
        assert expected_detail in response.json()["detail"]
        assert await _stored_permissions(db_session, member_user.id) == [
            ("tasks", True, False),
        ]
