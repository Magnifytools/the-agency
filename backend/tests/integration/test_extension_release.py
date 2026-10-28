"""Aviso de extensión nueva: en la propia extensión (también las viejas) y en la campana."""

import pytest
from sqlalchemy import select

from backend.db.models import Notification
from backend.services import extension_release
from backend.services.extension_package import read_version

pytestmark = pytest.mark.integration


def test_only_older_or_unversioned_extensions_are_outdated():
    assert extension_release.is_outdated(None, "2.4.0")
    assert extension_release.is_outdated("2.3.0", "2.4.0")
    assert extension_release.is_outdated("2.3.10", "2.4.0")
    assert not extension_release.is_outdated("2.4.0", "2.4.0")
    assert not extension_release.is_outdated("2.10.0", "2.4.0")
    assert extension_release.is_outdated("rara", "2.4.0")


async def test_old_extensions_get_the_update_notice_and_current_ones_do_not(admin_client):
    latest = read_version()
    old = (await admin_client.get("/api/communication-schedules/extension-upcoming")).json()
    notice = old["occurrences"][0]
    assert notice["occurrence_id"] == f"extension-update-{latest}"
    assert notice["title"] == f"Hay una versión nueva de la extensión ({latest})"
    assert notice["start_time"] is None and "Ajustes → Extensión de Chrome" in notice["content"]

    previous = (await admin_client.get("/api/communication-schedules/extension-upcoming",
                                       headers={"X-Agency-Extension-Version": "2.3.0"})).json()
    assert [item["occurrence_id"] for item in previous["occurrences"]] == [f"extension-update-{latest}"]
    current = (await admin_client.get("/api/communication-schedules/extension-upcoming",
                                      headers={"X-Agency-Extension-Version": latest})).json()
    assert current["occurrences"] == []


async def test_the_bell_announces_each_version_once_to_active_people(admin_client, member_user, db_session):
    member_user.is_active = False
    await db_session.flush()
    assert await extension_release.notify_release(db_session) == 1
    assert await extension_release.notify_release(db_session) == 0
    notice = (await db_session.execute(select(Notification).where(Notification.type == "extension_release"))).scalar_one()
    assert notice.user_id == admin_client.test_user.id
    assert notice.title == f"Nueva versión de la extensión de Chrome: {read_version()}"
    assert notice.link_url == "/settings#extension"
    await db_session.commit()
    assert [n["type"] for n in (await admin_client.get("/api/notifications")).json()] == ["extension_release"]
