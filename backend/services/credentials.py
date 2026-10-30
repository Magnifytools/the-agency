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
- La clave del autenticador (2FA) sigue las mismas reglas que la contraseña:
  cifrada (``totp_encrypted``) y sólo sale convertida en código por
  ``totp_code``, que también deja su fila en el registro.
- Las notas también van cifradas (``notes_encrypted``): suelen llevar códigos
  de recuperación o PIN. Los listados sólo dicen si hay (``has_notes``); se
  leen con ``reveal_notes``, que deja una fila "notes".
- ``secret_changed_at`` es el último cambio de contraseña. ``exposure`` lo
  compara con lo que una persona vio para decir qué hay que rotar cuando se va.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Iterable, Optional

from fastapi import HTTPException
from sqlalchemy import delete, exists, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.security import decrypt_vault_secret, encrypt_vault_secret
from backend.services import totp
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


def encrypt_notes(raw: Optional[str]) -> Optional[str]:
    """Las notas cifradas. Vacías → None (no se guarda un cifrado de nada)."""
    if raw is None or not raw.strip():
        return None
    return encrypt_vault_secret(raw)


def encrypt_totp(raw: Optional[str]) -> Optional[str]:
    """La clave del autenticador, comprobada y normalizada, cifrada. Vacía → None."""
    if raw is None or not raw.strip():
        return None
    try:
        config = totp.parse(raw)
    except totp.TotpError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    return encrypt_vault_secret(totp.to_uri(config))


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
    secret = decrypt(credential, credential.secret_encrypted)
    log(db, credential, user, purpose)
    await db.commit()
    return secret


async def reveal_notes(db: AsyncSession, user: User, credential: Credential) -> str:
    """Las notas en claro, con su fila "notes" en el registro antes de devolverlas."""
    if not credential.notes_encrypted:
        raise HTTPException(status_code=404, detail="Este acceso no tiene notas")
    notes = decrypt(credential, credential.notes_encrypted)
    log(db, credential, user, "notes")
    await db.commit()
    return notes


def decrypt(credential: Credential, value: str) -> str:
    try:
        return decrypt_vault_secret(value)
    except ValueError:
        # Ni el secreto ni el texto cifrado van al log.
        logger.warning("No se pudo descifrar el acceso %s (¿ha cambiado VAULT_KEY?)", credential.id)
        raise HTTPException(status_code=500, detail="No se pudo descifrar este acceso. Avisa a un admin.") from None


async def totp_code(db: AsyncSession, user: User, credential: Credential) -> dict:
    """El código 2FA de ahora (y el siguiente). Apunta quién y cuándo antes de devolverlo."""
    if not credential.totp_encrypted:
        raise HTTPException(status_code=404, detail="Este acceso no tiene código 2FA")
    try:
        config = totp.parse(decrypt(credential, credential.totp_encrypted))
    except totp.TotpError:
        raise HTTPException(status_code=500, detail="La clave 2FA guardada no es válida. Vuelve a ponerla.") from None
    log(db, credential, user, "totp")
    await db.commit()
    return totp.current(config)


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
        "has_notes": bool(c.notes_encrypted),
        "client_id": c.client_id,
        "client_name": clients.get(c.client_id),
        "created_by": c.created_by,
        "created_by_name": names.get(c.created_by),
        "updated_at": c.updated_at,
        "can_manage": c.id in managed,
        "has_totp": bool(c.totp_encrypted),
        "shared_with": shares.get(c.id, []),
    } for c in credentials]


# Lo que cuenta como "lo vio": ver o copiar la contraseña, pedir el código 2FA
# o abrir las notas. Crear o editar no cuenta (quien lo hace ya la conoce y lo
# dice el propio registro).
SEEN_ACTIONS = ("reveal", "copy", "totp", "notes")


async def exposure(db: AsyncSession, person_id: int) -> list[dict]:
    """Accesos que existen hoy y que esa persona vio o todavía puede ver.

    ``needs_rotation``: los vio y la contraseña no ha cambiado desde la última
    vez. Quien sólo los tiene compartidos sin haberlos abierto no obliga a
    rotar: basta con quitarle el acceso.
    """
    from sqlalchemy import func

    seen = (
        select(
            CredentialAccessLog.credential_id.label("credential_id"),
            func.max(CredentialAccessLog.at).label("last_seen_at"),
            func.count().label("times"),
        )
        .where(CredentialAccessLog.user_id == person_id, CredentialAccessLog.action.in_(SEEN_ACTIONS),
               CredentialAccessLog.credential_id.is_not(None))
        .group_by(CredentialAccessLog.credential_id)
        .subquery()
    )
    shared = exists().where(CredentialShare.credential_id == Credential.id, CredentialShare.user_id == person_id)
    rows = (await db.execute(
        select(Credential, Client.name, seen.c.last_seen_at, seen.c.times, shared.label("shared"))
        .outerjoin(seen, seen.c.credential_id == Credential.id)
        .outerjoin(Client, Client.id == Credential.client_id)
        .where(or_(seen.c.credential_id.is_not(None), shared, Credential.created_by == person_id))
        .order_by(seen.c.last_seen_at.desc().nulls_last(), Credential.name)
    )).all()
    return [{
        "id": credential.id,
        "name": credential.name,
        "url": credential.url,
        "client_name": client_name,
        "last_seen_at": last_seen_at,
        "times_seen": times or 0,
        "shared_with_them": bool(is_shared),
        "created_by_them": credential.created_by == person_id,
        "secret_changed_at": credential.secret_changed_at,
        "needs_rotation": last_seen_at is not None and credential.secret_changed_at <= last_seen_at,
    } for credential, client_name, last_seen_at, times, is_shared in rows]


async def revoke_shares(db: AsyncSession, admin: User, person: User) -> int:
    """Quita a esa persona de todos los accesos compartidos, con su fila "share"
    en el registro de cada uno. Los que creó siguen siendo suyos: un admin los
    reasigna o los borra."""
    credentials = list(await db.scalars(
        select(Credential).join(CredentialShare, CredentialShare.credential_id == Credential.id)
        .where(CredentialShare.user_id == person.id).order_by(Credential.id).with_for_update(of=Credential)
    ))
    if not credentials:
        return 0
    await db.execute(delete(CredentialShare).where(CredentialShare.user_id == person.id))
    for credential in credentials:
        log(db, credential, admin, "share", share_detail([], [person.full_name]))
    await db.commit()
    return len(credentials)
