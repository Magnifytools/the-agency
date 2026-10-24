"""Buzón de sugerencias: cualquiera envía, los admins ven todo y marcan hecho."""
import pytest
from sqlalchemy import select

from backend.db.models import AppSuggestion, InboxNote, InboxNoteStatus, Notification

pytestmark = pytest.mark.integration


async def test_member_sends_admins_get_notified_and_only_admin_resolves(
    admin_client, member_client, db_session,
):
    sent = await member_client.post("/api/suggestions", json={
        "text": "  Al subir un informe en HTML no pasa nada  ", "page_path": "/clients/12?tab=contexto",
    })
    assert sent.status_code == 201, sent.text
    body = sent.json()
    assert body["text"] == "Al subir un informe en HTML no pasa nada"
    assert body["author_name"] == "Member Integration"
    assert body["page_path"] == "/clients/12?tab=contexto"
    assert body["done_at"] is None

    notif = await db_session.scalar(select(Notification).where(
        Notification.user_id == admin_client.test_user.id, Notification.type == "app_suggestion",
    ))
    assert notif.link_url == "/sugerencias"
    assert notif.message == body["text"]
    # Quien la envía no se avisa a sí mismo.
    assert await db_session.scalar(select(Notification.id).where(
        Notification.user_id == member_client.test_user.id,
    )) is None

    # Un miembro no la marca como hecha.
    assert (await member_client.patch(f"/api/suggestions/{body['id']}", json={"done": True})).status_code == 403

    done = await admin_client.patch(f"/api/suggestions/{body['id']}", json={"done": True})
    assert done.status_code == 200
    assert done.json()["done_at"] is not None
    assert done.json()["done_by_name"] == "Admin Integration"
    told = await db_session.scalar(select(Notification).where(
        Notification.user_id == member_client.test_user.id, Notification.type == "app_suggestion_done",
    ))
    assert told.link_url == "/sugerencias"

    # Marcarla otra vez no repite el aviso; reabrir la vuelve a pendientes.
    await admin_client.patch(f"/api/suggestions/{body['id']}", json={"done": True})
    assert len((await db_session.scalars(select(Notification).where(
        Notification.type == "app_suggestion_done",
    ))).all()) == 1
    reopened = await admin_client.patch(f"/api/suggestions/{body['id']}", json={"done": False})
    assert reopened.json()["done_at"] is None and reopened.json()["done_by_name"] is None


async def test_lists_admins_see_all_members_only_theirs(admin_client, member_client):
    await member_client.post("/api/suggestions", json={"text": "De Nacho"})
    mine = (await admin_client.post("/api/suggestions", json={"text": "De David"})).json()
    await admin_client.patch(f"/api/suggestions/{mine['id']}", json={"done": True})

    assert [s["text"] for s in (await admin_client.get("/api/suggestions")).json()] == ["De Nacho"]
    assert [s["text"] for s in (await admin_client.get("/api/suggestions?status=done")).json()] == ["De David"]
    assert {s["text"] for s in (await admin_client.get("/api/suggestions?status=all")).json()} == {"De Nacho", "De David"}
    assert [s["text"] for s in (await member_client.get("/api/suggestions?status=all")).json()] == ["De Nacho"]


async def test_rejects_blank_text_and_external_paths(member_client):
    assert (await member_client.post("/api/suggestions", json={"text": "   "})).status_code == 422
    assert (await member_client.post("/api/suggestions", json={"text": "x" * 4001})).status_code == 422
    sent = await member_client.post("/api/suggestions", json={"text": "Idea", "page_path": "//evil.example/x"})
    assert sent.json()["page_path"] is None
    assert (await member_client.patch("/api/suggestions/999999", json={"done": True})).status_code == 403


async def test_inbox_suggestion_lands_in_the_same_list(admin_client, member_client, db_session):
    note = InboxNote(user_id=member_client.test_user.id, raw_text="Exportar a CSV", status=InboxNoteStatus.pending)
    db_session.add(note)
    await db_session.flush()

    response = await member_client.post(f"/api/inbox/{note.id}/suggest")
    assert response.status_code == 200
    assert response.json()["resolved_as"] == "app_suggestion"

    rows = (await db_session.scalars(select(AppSuggestion))).all()
    assert [(r.text, r.author_id) for r in rows] == [("Exportar a CSV", member_client.test_user.id)]
    listed = (await admin_client.get("/api/suggestions")).json()
    assert [s["text"] for s in listed] == ["Exportar a CSV"]

    # Repetir la acción no duplica la sugerencia.
    await member_client.post(f"/api/inbox/{note.id}/suggest")
    assert len((await db_session.scalars(select(AppSuggestion))).all()) == 1


PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def _image(name="pantallazo.png", content=PNG, mime="image/png"):
    return {"file": (name, content, mime)}


async def test_pantallazos_los_ve_quien_la_escribio_y_los_admins(admin_client, member_client, make_member_client):
    sent = (await member_client.post("/api/suggestions", json={"text": "Mira este fallo"})).json()
    added = await member_client.post(f"/api/suggestions/{sent['id']}/images", files=_image())
    assert added.status_code == 201, added.text
    image = added.json()
    assert image["name"] == "pantallazo.png" and image["size_bytes"] == len(PNG)

    listed = (await admin_client.get("/api/suggestions")).json()
    assert listed[0]["images"] == [image]

    url = f"/api/suggestions/{sent['id']}/images/{image['id']}"
    for client in (member_client, admin_client):
        got = await client.get(url)
        assert got.status_code == 200 and got.content == PNG
        assert got.headers["content-type"] == "image/png"
        assert got.headers["x-content-type-options"] == "nosniff"
        assert got.headers["content-disposition"].startswith("inline")

    # Otro miembro ni la ve ni le añade nada: el mismo 404.
    other = await make_member_client([])
    assert (await other.get(url)).status_code == 404
    assert (await other.post(f"/api/suggestions/{sent['id']}/images", files=_image())).status_code == 404
    await other.aclose()


async def test_solo_imagenes_cinco_como_mucho_y_hasta_5_mb(member_client):
    sent = (await member_client.post("/api/suggestions", json={"text": "Con capturas"})).json()
    url = f"/api/suggestions/{sent['id']}/images"
    for bad in (_image("informe.html", b"<script>alert(1)</script>", "text/html"),
                _image("informe.pdf", b"%PDF-1.4", "application/pdf"),
                _image("dibujo.svg", b"<svg/>", "image/svg+xml")):
        assert (await member_client.post(url, files=bad)).status_code == 415
    big = await member_client.post(url, files=_image(content=b"\x00" * (5 * 1024 * 1024 + 1)))
    assert big.status_code == 413
    for n in range(5):
        assert (await member_client.post(url, files=_image(f"captura-{n}.png"))).status_code == 201
    sixth = await member_client.post(url, files=_image("captura-6.png"))
    assert sixth.status_code == 409 and "5 imágenes" in sixth.json()["detail"]
