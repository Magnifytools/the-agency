"""Direct receipts expose only controls the current reader may execute."""
from datetime import date
from uuid import uuid4

from backend.db.models import Client, Delivery, WeeklyDigest
from backend.services.temporal import utc_now_naive


async def test_single_receipt_actions_follow_current_source_write_permission(db_session, make_member_client):
    member = await make_member_client([("digests", True, False)])
    try:
        client = Client(name="Synthetic receipt permissions")
        db_session.add(client)
        await db_session.flush()
        source = WeeklyDigest(client_id=client.id, created_by=member.test_user.id,
                              period_start=date(2026, 9, 7), period_end=date(2026, 9, 13))
        db_session.add(source)
        await db_session.flush()
        receipt = Delivery(id=str(uuid4()), dedupe_key=uuid4().hex, actor_id=member.test_user.id,
                           source_kind="digest", source_id=source.id, source_version="v1",
                           destination_key="isolated", payload={"text": "Original", "steps": []},
                           status="uncertain", available_at=utc_now_naive(), expires_at=utc_now_naive())
        db_session.add(receipt)
        await db_session.commit()
        url = f"/api/deliveries/{receipt.id}"
        response = await member.get(url)
        assert response.status_code == 200, response.text
        assert response.json()["content"] == "Original"
        assert not any(response.json()[key] for key in ("can_retry", "can_cancel", "can_resend"))
        assert (await member.post(f"{url}/resend", json={"reviewed": True, "review_key": str(uuid4())})).status_code == 403
        permission = next(p for p in member.test_user.permissions if p.module == "digests")
        permission.can_write = True
        await db_session.commit()
        assert (await member.get(url)).json()["can_resend"] is True
        permission.can_read = False
        await db_session.commit()
        assert (await member.get(url)).status_code == 403
    finally:
        await member.aclose()
