"""Accesos: credenciales compartidas (ver ``backend/services/credentials.py``)."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import require_admin, require_module
from backend.core.rate_limiter import credential_reveal_limiter
from backend.db.database import get_db
from backend.db.models import Client, Credential, CredentialAccessLog, User
from backend.schemas.credential import (
    CredentialCreate,
    CredentialImport,
    CredentialImportResult,
    CredentialTotpResponse,
    CredentialLogEntry,
    CredentialResponse,
    CredentialRevealRequest,
    CredentialRevealResponse,
    CredentialSharesUpdate,
    CredentialUpdate,
    SharedUser,
)
from backend.services import credentials as svc

router = APIRouter(prefix="/api/credentials", tags=["credentials"])

# Ni cachés ni historial: la respuesta lleva una contraseña en claro.
_NO_STORE = {"Cache-Control": "no-store", "Pragma": "no-cache"}
_REVEALS_PER_MINUTE = 30

_FIELD_LABELS = {"name": "nombre", "url": "URL", "username": "usuario", "notes": "notas",
                 "client_id": "cliente", "secret": "contraseña"}
_IMPORT_SOURCES = {"1password": "1Password", "bitwarden": "Bitwarden", "chrome": "Chrome", "csv": "un CSV"}


async def _one(db: AsyncSession, user: User, credential: Credential) -> dict:
    return (await svc.serialize(db, user, [credential]))[0]


@router.get("", response_model=list[CredentialResponse])
async def list_credentials(
    q: Optional[str] = Query(None, max_length=200),
    client_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_module(svc.MODULE)),
):
    """Las entradas que puede ver quien pregunta. Nunca lleva contraseñas."""
    query = select(Credential).outerjoin(Client, Client.id == Credential.client_id).where(svc.visible_filter(user))
    if client_id is not None:
        query = query.where(Credential.client_id == client_id)
    if q and q.strip():
        like = f"%{q.strip()}%"
        query = query.where(or_(Credential.name.ilike(like), Credential.url.ilike(like),
                                Credential.username.ilike(like), Client.name.ilike(like)))
    credentials = list(await db.scalars(query.order_by(Credential.name, Credential.id)))
    return await svc.serialize(db, user, credentials)


@router.get("/shareable-users", response_model=list[SharedUser])
async def list_shareable_users(
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_module(svc.MODULE, write=True)),
):
    return [{"id": u.id, "full_name": u.full_name} for u in await svc.shareable_users(db)]


@router.post("", response_model=CredentialResponse, status_code=status.HTTP_201_CREATED)
async def create_credential(
    body: CredentialCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_module(svc.MODULE, write=True)),
):
    await svc.ensure_client(db, body.client_id)
    targets = await svc.validate_share_targets(db, body.shared_user_ids)
    now = datetime.now(UTC)
    credential = Credential(
        name=body.name, url=body.url, username=body.username, notes=body.notes,
        secret_encrypted=svc.encrypt_secret(body.secret.get_secret_value()),
        totp_encrypted=svc.encrypt_totp(body.totp.get_secret_value() if body.totp else None),
        client_id=body.client_id, created_by=user.id, updated_by=user.id, created_at=now, updated_at=now,
    )
    db.add(credential)
    await db.flush()
    added, _ = await svc.replace_shares(db, credential, targets)
    svc.log(db, credential, user, "create", svc.share_detail(added, []))
    await db.commit()
    return await _one(db, user, credential)


@router.post("/import", response_model=CredentialImportResult, status_code=status.HTTP_201_CREATED)
async def import_credentials(
    body: CredentialImport,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_module(svc.MODULE, write=True)),
):
    """Alta en bloque desde un CSV de 1Password, Bitwarden o Chrome, ya leído en
    el navegador. Todo o nada: una fila mal y no se guarda ninguna (el mensaje
    dice cuál). Cada acceso queda a nombre de quien importa y con su "create"."""
    targets = await svc.validate_share_targets(db, body.shared_user_ids)
    client_ids = {item.client_id for item in body.items if item.client_id is not None}
    if client_ids:
        found = set(await db.scalars(select(Client.id).where(Client.id.in_(client_ids))))
        if client_ids - found:
            raise HTTPException(status_code=422, detail="Cliente no encontrado")
    now = datetime.now(UTC)
    detail = f"Importado de {_IMPORT_SOURCES[body.source]}"
    # Primero se comprueban y cifran TODAS; sólo después se añade nada a la sesión.
    encrypted = []
    for index, item in enumerate(body.items, start=1):
        try:
            encrypted.append((svc.encrypt_secret(item.secret.get_secret_value()),
                              svc.encrypt_totp(item.totp.get_secret_value() if item.totp else None)))
        except HTTPException as exc:
            raise HTTPException(status_code=422, detail=f"Fila {index} («{item.name}»): {exc.detail}") from None
    created = [
        Credential(
            name=item.name, url=item.url, username=item.username, notes=item.notes,
            secret_encrypted=secret, totp_encrypted=totp_value, client_id=item.client_id,
            created_by=user.id, updated_by=user.id, created_at=now, updated_at=now,
        )
        for item, (secret, totp_value) in zip(body.items, encrypted)
    ]
    db.add_all(created)
    await db.flush()
    for credential in created:
        added, _ = await svc.replace_shares(db, credential, targets)
        svc.log(db, credential, user, "create", " · ".join(filter(None, [detail, svc.share_detail(added, [])])))
    await db.commit()
    return {"created": len(created)}


@router.patch("/{credential_id}", response_model=CredentialResponse)
async def update_credential(
    credential_id: int,
    body: CredentialUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_module(svc.MODULE, write=True)),
):
    credential = await svc.get_manageable(db, user, credential_id)
    sent = body.model_fields_set
    changed: list[str] = []
    if "name" in sent and body.name is None:
        raise HTTPException(status_code=422, detail="El nombre no puede estar vacío")
    if "client_id" in sent:
        await svc.ensure_client(db, body.client_id)
    for field in ("name", "url", "username", "notes", "client_id"):
        if field in sent and getattr(credential, field) != getattr(body, field):
            setattr(credential, field, getattr(body, field))
            changed.append(_FIELD_LABELS[field])
    if "secret" in sent and body.secret is not None:
        credential.secret_encrypted = svc.encrypt_secret(body.secret.get_secret_value())
        changed.append(_FIELD_LABELS["secret"])
    if "totp" in sent:
        new_totp = svc.encrypt_totp(body.totp.get_secret_value() if body.totp else None)
        if new_totp is not None:
            credential.totp_encrypted = new_totp
            changed.append("código 2FA")
        elif credential.totp_encrypted is not None:
            credential.totp_encrypted = None
            changed.append("código 2FA (quitado)")
    if changed:
        credential.updated_at = datetime.now(UTC)
        credential.updated_by = user.id
        svc.log(db, credential, user, "update", "Cambió: " + ", ".join(changed))
        await db.commit()
    return await _one(db, user, credential)


@router.put("/{credential_id}/shares", response_model=CredentialResponse)
async def update_shares(
    credential_id: int,
    body: CredentialSharesUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_module(svc.MODULE, write=True)),
):
    credential = await svc.get_manageable(db, user, credential_id)
    targets = await svc.validate_share_targets(db, body.user_ids)
    added, removed = await svc.replace_shares(db, credential, targets)
    if added or removed:
        svc.log(db, credential, user, "share", svc.share_detail(added, removed))
    await db.commit()
    return await _one(db, user, credential)


@router.post("/{credential_id}/reveal", response_model=CredentialRevealResponse)
async def reveal_credential(
    credential_id: int,
    response: Response,
    body: Optional[CredentialRevealRequest] = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_module(svc.MODULE)),
):
    """Devuelve la contraseña una vez y deja rastro (ver o copiar)."""
    credential_reveal_limiter.check(user.id, _REVEALS_PER_MINUTE, 60)
    credential = await svc.get_visible(db, user, credential_id)
    secret = await svc.reveal_secret(db, user, credential, body.purpose if body else "reveal")
    response.headers.update(_NO_STORE)
    return {"secret": secret}


@router.post("/{credential_id}/totp", response_model=CredentialTotpResponse)
async def credential_totp(
    credential_id: int,
    response: Response,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_module(svc.MODULE)),
):
    """El código 2FA de ahora y el siguiente. Como ver la contraseña: quien lo
    puede ver, con el mismo límite por minuto y su fila en el registro."""
    credential_reveal_limiter.check(user.id, _REVEALS_PER_MINUTE, 60)
    credential = await svc.get_visible(db, user, credential_id)
    code = await svc.totp_code(db, user, credential)
    response.headers.update(_NO_STORE)
    return code


@router.get("/{credential_id}/log", response_model=list[CredentialLogEntry])
async def credential_log(
    credential_id: int,
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    if await db.scalar(select(Credential.id).where(Credential.id == credential_id)) is None:
        raise HTTPException(status_code=404, detail="Acceso no encontrado")
    rows = (await db.execute(
        select(CredentialAccessLog, User.full_name)
        .outerjoin(User, User.id == CredentialAccessLog.user_id)
        .where(CredentialAccessLog.credential_id == credential_id)
        .order_by(CredentialAccessLog.at.desc(), CredentialAccessLog.id.desc())
        .limit(limit)
    )).all()
    return [{"id": entry.id, "action": entry.action, "user_id": entry.user_id, "user_name": name,
             "detail": entry.detail, "at": entry.at} for entry, name in rows]


@router.delete("/{credential_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_credential(
    credential_id: int,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Borrado definitivo (sólo admin). El registro se queda con el nombre."""
    credential = await svc.get_visible(db, admin, credential_id, lock=True)
    svc.log(db, credential, admin, "delete")
    await db.flush()
    await db.delete(credential)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
