from backend.db.models import InboxAttachment, InboxNote, InboxNoteStatus
from backend.api.routes.inbox import MAX_ATTACHMENT_SIZE


async def _note(db_session, user_id: int) -> InboxNote:
    note = InboxNote(
        user_id=user_id,
        raw_text="Adjuntos seguros",
        status=InboxNoteStatus.pending,
    )
    db_session.add(note)
    await db_session.flush()
    return note


async def test_legacy_active_content_downloads_as_opaque_bytes(
    admin_client, db_session,
):
    note = await _note(db_session, admin_client.test_user.id)
    for name, mime_type, content in (
        ('informe "final".svg', "image/svg+xml", b"<svg><script>alert(1)</script></svg>"),
        ("página.html", "text/html", b"<script>alert(1)</script>"),
    ):
        attachment = InboxAttachment(
            note_id=note.id,
            name=name,
            mime_type=mime_type,
            size_bytes=len(content),
            content=content,
            uploaded_by=admin_client.test_user.id,
        )
        db_session.add(attachment)
        await db_session.flush()

        response = await admin_client.get(
            f"/api/inbox/{note.id}/attachments/{attachment.id}",
        )
        assert response.status_code == 200
        assert response.content == content
        assert response.headers["content-type"] == "application/octet-stream"
        assert response.headers["content-disposition"].startswith(
            "attachment; filename*=UTF-8''",
        )
        assert '"' not in response.headers["content-disposition"]
        assert response.headers["x-content-type-options"] == "nosniff"


async def test_only_known_raster_and_sandboxed_pdf_render_inline(
    admin_client, db_session,
):
    note = await _note(db_session, admin_client.test_user.id)
    fixtures = (
        ("captura.png", "image/png", None),
        ("documento.pdf", "application/pdf", "sandbox; default-src 'none'"),
    )
    for name, mime_type, csp in fixtures:
        attachment = InboxAttachment(
            note_id=note.id,
            name=name,
            mime_type=mime_type,
            size_bytes=4,
            content=b"safe",
            uploaded_by=admin_client.test_user.id,
        )
        db_session.add(attachment)
        await db_session.flush()

        response = await admin_client.get(
            f"/api/inbox/{note.id}/attachments/{attachment.id}",
        )
        assert response.status_code == 200
        assert response.headers["content-type"].startswith(mime_type)
        assert response.headers["content-disposition"].startswith("inline;")
        if csp:
            assert response.headers["content-security-policy"] == csp


async def test_attachment_download_requires_note_ownership(
    admin_client, member_client, db_session,
):
    note = await _note(db_session, admin_client.test_user.id)
    attachment = InboxAttachment(
        note_id=note.id,
        name="privado.png",
        mime_type="image/png",
        size_bytes=4,
        content=b"safe",
        uploaded_by=admin_client.test_user.id,
    )
    db_session.add(attachment)
    await db_session.flush()

    response = await member_client.get(
        f"/api/inbox/{note.id}/attachments/{attachment.id}",
    )
    assert response.status_code == 404


async def test_upload_bounds_size_and_metadata(admin_client, db_session):
    note = await _note(db_session, admin_client.test_user.id)

    response = await admin_client.post(
        f"/api/inbox/{note.id}/attachments",
        files={"file": ("large.bin", b"x" * (MAX_ATTACHMENT_SIZE + 1), "application/octet-stream")},
    )
    assert response.status_code == 400
    assert "10 mb" in response.text.lower()

    long_name = "a" * 256 + ".txt"
    response = await admin_client.post(
        f"/api/inbox/{note.id}/attachments",
        files={"file": (long_name, b"small", "text/plain")},
    )
    assert response.status_code == 400
    assert "nombre" in response.text.lower()

    long_mime = "application/" + "x" * 100
    response = await admin_client.post(
        f"/api/inbox/{note.id}/attachments",
        files={"file": ("small.bin", b"small", long_mime)},
    )
    assert response.status_code == 400
    assert "tipo" in response.text.lower()
