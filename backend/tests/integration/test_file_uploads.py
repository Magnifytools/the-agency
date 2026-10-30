"""Adjuntos de tareas y documentos de cliente: HTML y ZIP se suben y nunca se
ejecutan en nuestro origen; lo que no se admite da un motivo legible."""
from uuid import uuid4

import pytest
from sqlalchemy import select

from backend.api.routes.tasks import MAX_ATTACHMENT_BYTES
from backend.db.models import (
    Client, ClientDocument, Project, Task, TaskAttachment, TaskPriority, TaskStatus,
)

pytestmark = pytest.mark.integration

REPORT = b"<html><body><script>alert(document.cookie)</script>Informe</body></html>"


async def _task(db, user_id) -> Task:
    client = Client(name=f"Upload client {uuid4().hex[:8]}")
    project = Project(name=f"Upload project {uuid4().hex[:8]}", client=client)
    db.add_all([client, project])
    await db.flush()
    task = Task(
        title="Informe mensual", client_id=client.id, project_id=project.id,
        created_by=user_id, status=TaskStatus.pending, priority=TaskPriority.medium,
    )
    db.add(task)
    await db.flush()
    return task


def _assert_opaque_download(response, content: bytes):
    assert response.status_code == 200
    assert response.content == content
    assert response.headers["content-type"] == "application/octet-stream"
    assert response.headers["content-disposition"].startswith("attachment; filename*=UTF-8''")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["content-security-policy"] == "sandbox; default-src 'none'"


@pytest.mark.parametrize("name,browser_type,stored", [
    ("informe-septiembre.html", "text/html", "text/html"),
    ("informe.htm", "text/html", "text/html"),
    # Windows manda x-zip-compressed y algunos navegadores octet-stream: el
    # tipo sale de la extensión, no de lo que diga el navegador.
    ("informe.zip", "application/x-zip-compressed", "application/zip"),
    ("informe.ZIP", "application/octet-stream", "application/zip"),
])
async def test_task_accepts_html_and_zip_reports(admin_client, db_session, name, browser_type, stored):
    task = await _task(db_session, admin_client.test_user.id)
    response = await admin_client.post(
        f"/api/tasks/{task.id}/attachments", files={"file": (name, REPORT, browser_type)},
    )
    assert response.status_code == 201, response.text
    assert response.json()["mime_type"] == stored
    row = await db_session.scalar(select(TaskAttachment).where(TaskAttachment.task_id == task.id))
    assert row.content == REPORT and row.mime_type == stored


async def test_uploaded_html_never_renders_in_our_origin(admin_client, db_session):
    task = await _task(db_session, admin_client.test_user.id)
    created = (await admin_client.post(
        f"/api/tasks/{task.id}/attachments",
        files={"file": ("informe “final” — oct.html", REPORT, "text/html")},
    )).json()
    base = f"/api/tasks/{task.id}/attachments/{created['id']}"
    _assert_opaque_download(await admin_client.get(f"{base}/download"), REPORT)
    # La vista previa tampoco lo pinta: sólo PDF e imágenes van inline.
    _assert_opaque_download(await admin_client.get(f"{base}/preview"), REPORT)


async def test_task_preview_still_shows_pdf_inline_sandboxed(admin_client, db_session):
    task = await _task(db_session, admin_client.test_user.id)
    created = (await admin_client.post(
        f"/api/tasks/{task.id}/attachments", files={"file": ("factura.pdf", b"%PDF-1.4", "application/pdf")},
    )).json()
    response = await admin_client.get(f"/api/tasks/{task.id}/attachments/{created['id']}/preview")
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"].startswith("inline;")
    assert response.headers["content-security-policy"] == "sandbox; default-src 'none'"


async def test_rejections_say_why(admin_client, db_session):
    task = await _task(db_session, admin_client.test_user.id)
    url = f"/api/tasks/{task.id}/attachments"

    bad_type = await admin_client.post(url, files={"file": ("setup.exe", b"MZ", "application/x-msdownload")})
    assert bad_type.status_code == 415
    assert bad_type.json()["detail"].startswith("No se admiten archivos .exe.")
    assert "HTML o ZIP" in bad_type.json()["detail"]

    too_big = await admin_client.post(
        url, files={"file": ("grande.zip", b"0" * (MAX_ATTACHMENT_BYTES + 1), "application/zip")},
    )
    assert too_big.status_code == 413
    assert too_big.json()["detail"] == "El archivo supera el límite de 10 MB"

    long_name = await admin_client.post(url, files={"file": ("a" * 260 + ".pdf", b"%PDF", "application/pdf")})
    assert long_name.status_code == 400
    assert await db_session.scalar(select(TaskAttachment.id).where(TaskAttachment.task_id == task.id)) is None


async def test_client_documents_accept_html_and_zip_and_download_opaque(admin_client, db_session):
    client = Client(name=f"Docs client {uuid4().hex[:8]}")
    db_session.add(client)
    await db_session.flush()
    url = f"/api/clients/{client.id}/documents"

    for name, browser_type in (("informe.html", "text/html"), ("entregables.zip", "application/x-zip-compressed")):
        response = await admin_client.post(url, files={"file": (name, REPORT, browser_type)})
        assert response.status_code == 201, response.text

    doc = await db_session.scalar(select(ClientDocument).where(
        ClientDocument.client_id == client.id, ClientDocument.name == "informe.html",
    ))
    assert doc.mime_type == "text/html"
    _assert_opaque_download(await admin_client.get(f"{url}/{doc.id}/download"), REPORT)

    rejected = await admin_client.post(url, files={"file": ("macro.js", b"x", "text/javascript")})
    assert rejected.status_code == 415
    assert rejected.json()["detail"].startswith("No se admiten archivos .js.")
