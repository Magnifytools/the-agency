"""Accesos: credenciales compartidas, cifradas en el servidor.

Reglas (decididas por David):
- Acceso POR ENTRADA. Un admin ve y gestiona todas; el resto sólo las que ha
  creado o le han compartido. Lo que no puede ver es un 404, no un 403: no se
  confirma ni que exista.
- Crear pide escritura en ``credentials``; editar y compartir, además, ser admin
  o quien la creó. Borrar (definitivo) sólo un admin.
- El secreto sólo existe cifrado con ``encrypt_vault_secret`` (``VAULT_KEY``).
  Ninguna respuesta de listado o detalle lo lleva; sólo ``reveal_secret``, que
  deja una fila en ``credential_access_log`` ANTES de devolverlo.
- Nada de esto pasa por el journal de Deshacer (no está en ``_SPECS``): el
  journal guarda valores viejos y nuevos de columnas en JSON y un secreto no
  puede acabar ahí, ni cifrado (el undo lo podría restaurar tras una rotación).
- Nunca se escribe el secreto en logs ni en mensajes de error.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Iterable, Optional

from fastapi import HTTPException
from sqlalchemy import delete, exists, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.security import decrypt_vault_secret, encrypt_vault_secret
from backend.db.models import (
    Client,
    Credential,
    CredentialAccessLog,
    CredentialShare,
    User,
    UserPermission,
    UserRole,
)

logger = logging.getLogger(__name__)

MODULE = "credentials"
MAX_SECRET_LENGTH = 2000
_NOT_FOUND = "Acceso no encontrado"


def is_admin(user: User) -> bool:
    return user.role == UserRole.admin


def visible_filter(user: User):
    """Condición SQL de "este usuario puede ver la entrada"."""
    if is_admin(user):
        return true()
    shared = exists().where(
        CredentialShare.credential_id == Credential.id, CredentialShare.user_id == user.id,
    )
    return or_(Credential.created_by == user.id, shared)


def can_manage(user: User, credential: Credential) -> bool:
    return is_admin(user) or (credential.created_by is not None and credential.created_by == user.id)


def encrypt_secret(raw: str) -> str:
    if not raw:
        raise HTTPException(status_code=422, detail="La contraseña no puede estar vacía")
    if len(raw) > MAX_SECRET_LENGTH:
        raise HTTPException(status_code=422, detail=f"La contraseña no puede pasar de {MAX_SECRET_LENGTH} caracteres")
    return encrypt_vault_secret(raw)


async def get_visible(db: AsyncSession, user: User, credential_id: int, *, lock: bool = False) -> Credential:
    query = select(Credential).where(Credential.id == credential_id, visible_filter(user))
    if lock:
        query = query.with_for_update(of=Credential)
    credential = await db.scalar(query)
    if credential is None:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    return credential


async def get_manageable(db: AsyncSession, user: User, credential_id: int) -> Credential:
    credential = await get_visible(db, user, credential_id, lock=True)
    if not can_manage(user, credential):
        raise HTTPException(status_code=403, detail="Sólo quien creó este acceso o un admin puede cambiarlo")
    return credential


async def ensure_client(db: AsyncSession, client_id: Optional[int]) -> None:
    if client_id is not None and await db.scalar(select(Client.id).where(Client.id == client_id)) is None:
        raise HTTPException(status_code=422, detail="Cliente no encontrado")


async def shareable_users(db: AsyncSession) -> list[User]:
    """Usuarios activos que pueden abrir Accesos: admins o con lectura del módulo."""
    has_read = exists().where(
        UserPermission.user_id == User.id, UserPermission.module == MODULE, UserPermission.can_read.is_(True),
    )
    rows = await db.scalars(
        select(User).where(User.is_active.is_(True), or_(User.role == UserRole.admin, has_read))
        .order_by(User.full_name)
    )
    return list(rows)


async def validate_share_targets(db: AsyncSession, user_ids: Iterable[int]) -> list[User]:
    wanted = set(user_ids)
    if not wanted:
        return []
    allowed = {u.id: u for u in await shareable_users(db)}
    invalid = wanted - allowed.keys()
    if invalid:
        raise HTTPException(
            status_code=422,
            detail="Sólo se puede compartir con usuarios activos que tengan acceso al módulo Accesos",
        )
    return sorted((allowed[i] for i in wanted), key=lambda u: u.full_name)


async def replace_shares(db: AsyncSession, credential: Credential, users: list[User]) -> tuple[list[str], list[str]]:
    """Deja exactamente esos usuarios. Devuelve (añadidos, quitados) por nombre."""
    current_ids = set(await db.scalars(
        select(CredentialShare.user_id).where(CredentialShare.credential_id == credential.id)
    ))
    wanted_ids = {u.id for u in users}
    removed_ids = current_ids - wanted_ids
    added = [u for u in users if u.id not in current_ids]
    if removed_ids:
        await db.execute(delete(CredentialShare).where(
            CredentialShare.credential_id == credential.id, CredentialShare.user_id.in_(removed_ids),
        ))
    for target in added:
        db.add(CredentialShare(credential_id=credential.id, user_id=target.id))
    removed_names = sorted(await db.scalars(select(User.full_name).where(User.id.in_(removed_ids)))) if removed_ids else []
    return [u.full_name for u in added], removed_names


def share_detail(added: list[str], removed: list[str]) -> Optional[str]:
    parts = []
    if added:
        parts.append("Compartido con: " + ", ".join(added))
    if removed:
        parts.append("Quitado a: " + ", ".join(removed))
    return (" · ".join(parts))[:500] or None


def log(db: AsyncSession, credential: Credential, user: User, action: str, detail: Optional[str] = None) -> None:
    db.add(CredentialAccessLog(
        credential_id=credential.id, credential_name=credential.name, user_id=user.id,
        action=action, detail=detail, at=datetime.now(UTC),
    ))


async def reveal_secret(db: AsyncSession, user: User, credential: Credential, purpose: str) -> str:
    """Descifra, apunta quién y cuándo, confirma, y sólo entonces devuelve."""
    try:
        secret = decrypt_vault_secret(credential.secret_encrypted)
    except ValueError:
        # Ni el secreto ni el texto cifrado van al log.
        logger.warning("No se pudo descifrar el acceso %s (¿ha cambiado VAULT_KEY?)", credential.id)
        raise HTTPException(status_code=500, detail="No se pudo descifrar este acceso. Avisa a un admin.") from None
    log(db, credential, user, purpose)
    await db.commit()
    return secret


async def serialize(db: AsyncSession, user: User, credentials: list[Credential]) -> list[dict]:
    if not credentials:
        return []
    client_ids = {c.client_id for c in credentials if c.client_id}
    user_ids = {c.created_by for c in credentials if c.created_by}
    clients = dict((await db.execute(select(Client.id, Client.name).where(Client.id.in_(client_ids)))).all()) if client_ids else {}
    managed = [c.id for c in credentials if can_manage(user, c)]
    shares: dict[int, list[dict]] = {}
    if managed:
        rows = (await db.execute(
            select(CredentialShare.credential_id, User.id, User.full_name)
            .join(User, User.id == CredentialShare.user_id)
            .where(CredentialShare.credential_id.in_(managed))
            .order_by(User.full_name)
        )).all()
        for credential_id, uid, full_name in rows:
            shares.setdefault(credential_id, []).append({"id": uid, "full_name": full_name})
    names = dict((await db.execute(select(User.id, User.full_name).where(User.id.in_(user_ids)))).all()) if user_ids else {}
    return [{
        "id": c.id,
        "name": c.name,
        "url": c.url,
        "username": c.username,
        "notes": c.notes,
        "client_id": c.client_id,
        "client_name": clients.get(c.client_id),
        "created_by": c.created_by,
        "created_by_name": names.get(c.created_by),
        "updated_at": c.updated_at,
        "can_manage": c.id in managed,
        "shared_with": shares.get(c.id, []),
    } for c in credentials]
