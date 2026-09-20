import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_current_user
from backend.db.database import get_db
from backend.db.models import CommandReceipt, User
from backend.schemas.command import (
    CommandCreate, CommandExecute, CommandListResponse, CommandReceiptResponse, CommandResolve,
)
from backend.services.command_decisions import query_decisions
from backend.services.change_journal import prepare_entry
from backend.services.temporal import utc_now_naive
from backend.services.commands import (
    STATUS_EXECUTED, STATUS_FAILED, STATUS_INPUT, STATUS_REVIEW, apply_answers,
    check_step_replay, execute_or_prompt, parse_command, record_step, request_hash,
    query_work, require_permission, response_dict, step_hash,
)

router = APIRouter(prefix="/api/commands", tags=["commands"])


async def _owned_locked(db: AsyncSession, receipt_id: str, user_id: int) -> CommandReceipt:
    row = (await db.execute(select(CommandReceipt).where(
        CommandReceipt.id == receipt_id, CommandReceipt.user_id == user_id,
    ).with_for_update().execution_options(populate_existing=True))).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "Command receipt not found")
    return row


async def _execute_atomically(db: AsyncSession, row: CommandReceipt, actor: User, *, reviewed: bool = False) -> None:
    """Keep validation failures out of the outer receipt transaction."""
    nested = await db.begin_nested()
    try:
        await execute_or_prompt(db, row, actor, reviewed=reviewed)
        await nested.commit()
    except Exception:
        await nested.rollback()
        raise
    if row.status == STATUS_EXECUTED and (row.result or {}).get("entities"):
        journal = await db.run_sync(prepare_entry)
        row.change_log_id = journal.id if journal else None
        result = dict(row.result or {})
        result["undo_available"] = journal is not None
        row.result = result


async def _persist_failed_step(db: AsyncSession, receipt_id: str, user_id: int,
                               exc: HTTPException) -> None:
    """Keep a rejected resolve/execute visible without retaining its mutations."""
    await db.rollback()
    row = await _owned_locked(db, receipt_id, user_id)
    row.status = STATUS_FAILED
    row.error_code = "forbidden" if exc.status_code == 403 else "invalid_command"
    row.error_detail = str(exc.detail)
    row.revision += 1
    row.updated_at = utc_now_naive()
    await db.commit()


@router.post("", response_model=CommandReceiptResponse)
async def create_command(payload: CommandCreate, db: AsyncSession = Depends(get_db),
                         actor: User = Depends(get_current_user)):
    context = payload.context.model_dump(exclude_none=True) if payload.context else None
    digest = request_hash(payload.text, payload.channel, context)
    receipt_id = str(uuid.uuid4())
    inserted = await db.scalar(insert(CommandReceipt).values(
        id=receipt_id, user_id=actor.id, request_key=payload.request_key,
        request_hash=digest, channel=payload.channel, context=context,
        raw_text=payload.text.strip(), status=STATUS_INPUT,
        intent=parse_command(payload.text), revision=1, step_replays={},
        created_at=utc_now_naive(), updated_at=utc_now_naive(),
    ).on_conflict_do_nothing(index_elements=["user_id", "request_key"]).returning(CommandReceipt.id))
    if inserted is None:
        row = await db.scalar(select(CommandReceipt).where(
            CommandReceipt.user_id == actor.id, CommandReceipt.request_key == payload.request_key))
        if row.request_hash != digest:
            raise HTTPException(409, "La clave idempotente ya se usó con otro contenido")
        return response_dict(row)
    row = await _owned_locked(db, receipt_id, actor.id)
    try:
        await _execute_atomically(db, row, actor)
        row.updated_at = utc_now_naive()
        await db.commit()
    except HTTPException as exc:
        await db.refresh(row)
        row.status = STATUS_FAILED
        row.error_code = "forbidden" if exc.status_code == 403 else "invalid_command"
        row.error_detail = str(exc.detail)
        row.revision += 1
        row.updated_at = utc_now_naive()
        await db.commit()
        raise
    await db.refresh(row)
    return response_dict(row)


@router.post("/{receipt_id}/resolve", response_model=CommandReceiptResponse)
async def resolve_command(receipt_id: str, payload: CommandResolve,
                          db: AsyncSession = Depends(get_db), actor: User = Depends(get_current_user)):
    row = await _owned_locked(db, receipt_id, actor.id)
    body = payload.model_dump(exclude_none=True)
    digest = step_hash("resolve", payload.revision, body["answers"])
    if check_step_replay(row, payload.request_key, digest):
        return response_dict(row)
    if row.status != STATUS_INPUT:
        raise HTTPException(409, "El recibo ya no espera una respuesta")
    if row.revision != payload.revision:
        raise HTTPException(409, "El recibo cambió; vuelve a cargarlo")
    try:
        apply_answers(row, body["answers"])
        row.revision += 1
        await _execute_atomically(db, row, actor)
        record_step(row, payload.request_key, digest)
        row.updated_at = utc_now_naive()
        await db.commit()
    except HTTPException as exc:
        if exc.status_code == 403:
            await _persist_failed_step(db, receipt_id, actor.id, exc)
        else:
            await db.rollback()
        raise
    await db.refresh(row)
    return response_dict(row)


@router.post("/{receipt_id}/execute", response_model=CommandReceiptResponse)
async def execute_reviewed_command(receipt_id: str, payload: CommandExecute,
                                   db: AsyncSession = Depends(get_db), actor: User = Depends(get_current_user)):
    row = await _owned_locked(db, receipt_id, actor.id)
    digest = step_hash("execute", payload.revision, {})
    if check_step_replay(row, payload.request_key, digest):
        return response_dict(row)
    if row.status != STATUS_REVIEW:
        raise HTTPException(409, "El recibo no tiene una revisión ejecutable")
    if row.revision != payload.revision:
        raise HTTPException(409, "El recibo cambió; vuelve a cargarlo")
    try:
        row.revision += 1
        await _execute_atomically(db, row, actor, reviewed=True)
        record_step(row, payload.request_key, digest)
        row.updated_at = utc_now_naive()
        await db.commit()
    except HTTPException as exc:
        if exc.status_code in {403, 409}:
            await _persist_failed_step(db, receipt_id, actor.id, exc)
        else:
            await db.rollback()
        raise
    await db.refresh(row)
    return response_dict(row)


@router.get("/{receipt_id}", response_model=CommandReceiptResponse)
async def get_command(receipt_id: str, db: AsyncSession = Depends(get_db),
                      actor: User = Depends(get_current_user)):
    row = await db.scalar(select(CommandReceipt).where(
        CommandReceipt.id == receipt_id, CommandReceipt.user_id == actor.id))
    if row is None:
        raise HTTPException(404, "Command receipt not found")
    return response_dict(row)


@router.get("/{receipt_id}/query")
async def get_command_query(receipt_id: str, page: int = Query(1, ge=1),
                            page_size: int = Query(25, ge=1, le=100),
                            db: AsyncSession = Depends(get_db), actor: User = Depends(get_current_user)):
    row = await db.scalar(select(CommandReceipt).where(
        CommandReceipt.id == receipt_id, CommandReceipt.user_id == actor.id))
    if row is None:
        raise HTTPException(404, "Command receipt not found")
    if row.status != STATUS_EXECUTED or (row.intent or {}).get("kind") != "query_work":
        raise HTTPException(409, "El recibo no contiene una consulta")
    if row.intent["query"] == "decisions":
        return await query_decisions(db, actor, scope=row.intent.get("scope", "mine"),
                                     page=page, page_size=page_size)
    require_permission(actor, "tasks", write=False)
    return await query_work(db, row.intent["query"], actor=actor,
                            scope=row.intent.get("scope", "mine"), page=page, page_size=page_size)


@router.get("", response_model=CommandListResponse)
async def list_commands(status: str | None = None, page: int = Query(1, ge=1),
                        page_size: int = Query(25, ge=1, le=100),
                        db: AsyncSession = Depends(get_db), actor: User = Depends(get_current_user)):
    query = select(CommandReceipt).where(CommandReceipt.user_id == actor.id)
    if status:
        if status not in {STATUS_INPUT, STATUS_REVIEW, STATUS_EXECUTED, STATUS_FAILED}:
            raise HTTPException(422, "Estado de recibo no válido")
        query = query.where(CommandReceipt.status == status)
    total = await db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = list((await db.execute(query.order_by(CommandReceipt.created_at.desc())
                                  .offset((page - 1) * page_size).limit(page_size))).scalars().all())
    return {"items": [response_dict(row) for row in rows], "total": total,
            "page": page, "page_size": page_size, "has_more": page * page_size < total}
