"""Holded integration API routes."""
from datetime import datetime, date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.database import get_db
from backend.db.models import (
    Client, HoldedSyncLog, HoldedInvoiceCache, HoldedExpenseCache,
)
from backend.api.deps import get_current_user, require_admin
from backend.config import settings
from backend.services.holded_service import HoldedClient, HoldedError
from backend.schemas.holded import (
    SyncLogResponse, SyncStatusResponse, SyncResult,
    HoldedInvoiceResponse, HoldedExpenseResponse,
    HoldedDashboardResponse, MonthlyFinancials,
    HoldedConfigResponse, TestConnectionResponse,
)

router = APIRouter(prefix="/api/holded", tags=["holded"])


def _get_holded_client() -> HoldedClient:
    if not settings.HOLDED_API_KEY:
        raise HTTPException(status_code=400, detail="HOLDED_API_KEY no configurada")
    return HoldedClient(settings.HOLDED_API_KEY)


# ── Sync endpoints ─────────────────────────────────────────


@router.post("/sync/contacts", response_model=SyncResult)
async def sync_contacts(
    session: AsyncSession = Depends(get_db),
    user=Depends(require_admin),
):
    """Sync Holded contacts → Agency clients."""
    holded = _get_holded_client()
    log = HoldedSyncLog(sync_type="contacts", status="in_progress")
    session.add(log)
    await session.flush()

    try:
        contacts = await holded.list_contacts()
        synced = 0

        for contact in contacts:
            holded_id = contact.get("id", "")
            if not holded_id:
                continue

            # Check if client already linked
            result = await session.execute(
                select(Client).where(Client.holded_contact_id == holded_id)
            )
            existing = result.scalar_one_or_none()

            if existing:
                # Update existing client
                existing.name = contact.get("name", existing.name)
                existing.email = contact.get("email", existing.email)
                existing.phone = contact.get("phone", existing.phone)
                existing.vat_number = contact.get("vatnumber", existing.vat_number)
            else:
                # Try to match by name or email
                name = contact.get("name", "")
                email = contact.get("email", "")
                match_q = select(Client).where(
                    (Client.name == name) | ((Client.email == email) & (Client.email != None) & (Client.email != ""))
                )
                result = await session.execute(match_q)
                match = result.scalar_one_or_none()

                if match:
                    match.holded_contact_id = holded_id
                    match.vat_number = contact.get("vatnumber", match.vat_number)
                    if not match.phone and contact.get("phone"):
                        match.phone = contact["phone"]
                # Else: no match, skip (don't auto-create clients from Holded)

            synced += 1

        log.status = "success"
        log.records_synced = synced
        log.completed_at = datetime.utcnow()
        await session.commit()

        return SyncResult(sync_type="contacts", status="success", records_synced=synced)

    except HoldedError as e:
        log.status = "error"
        log.error_message = str(e)
        log.completed_at = datetime.utcnow()
        await session.commit()
        raise HTTPException(status_code=502, detail=f"Error de Holded: {e.detail}")


@router.post("/sync/invoices", response_model=SyncResult)
async def sync_invoices(
    session: AsyncSession = Depends(get_db),
    user=Depends(require_admin),
):
    """Sync Holded invoices → local cache."""
    holded = _get_holded_client()
    log = HoldedSyncLog(sync_type="invoices", status="in_progress")
    session.add(log)
    await session.flush()

    try:
        invoices = await holded.list_invoices()
        synced = 0

        for inv in invoices:
            holded_id = inv.get("id", "")
            if not holded_id:
                continue

            # Upsert
            result = await session.execute(
                select(HoldedInvoiceCache).where(HoldedInvoiceCache.holded_id == holded_id)
            )
            cached = result.scalar_one_or_none()

            # Try to match client by holded contact id
            contact_id = inv.get("contactId", "") or inv.get("contact", "")
            client_id = None
            contact_name_val = inv.get("contactName", "") or ""
            if contact_id:
                r = await session.execute(
                    select(Client.id).where(Client.holded_contact_id == str(contact_id))
                )
                row = r.scalar_one_or_none()
                if row:
                    client_id = row

            # Parse date (Holded returns unix timestamp)
            inv_date = _parse_holded_date(inv.get("date"))
            due_date = _parse_holded_date(inv.get("dueDate"))

            # Determine status
            status = "pending"
            if inv.get("paid"):
                status = "paid"
            elif due_date and due_date < date.today():
                status = "overdue"

            total = float(inv.get("total", 0) or 0)
            subtotal = float(inv.get("subtotal", 0) or 0)
            tax_val = float(inv.get("tax", 0) or 0)

            if cached:
                cached.client_id = client_id
                cached.contact_name = contact_name_val
                cached.invoice_number = inv.get("docNumber", cached.invoice_number)
                cached.date = inv_date
                cached.due_date = due_date
                cached.total = total
                cached.subtotal = subtotal
                cached.tax = tax_val
                cached.status = status
                cached.currency = inv.get("currency", "EUR") or "EUR"
                cached.raw_data = inv
                cached.synced_at = datetime.utcnow()
            else:
                session.add(HoldedInvoiceCache(
                    holded_id=holded_id,
                    client_id=client_id,
                    contact_name=contact_name_val,
                    invoice_number=inv.get("docNumber"),
                    date=inv_date,
                    due_date=due_date,
                    total=total,
                    subtotal=subtotal,
                    tax=tax_val,
                    status=status,
                    currency=inv.get("currency", "EUR") or "EUR",
                    raw_data=inv,
                ))

            synced += 1

        log.status = "success"
        log.records_synced = synced
        log.completed_at = datetime.utcnow()
        await session.commit()

        return SyncResult(sync_type="invoices", status="success", records_synced=synced)

    except HoldedError as e:
        log.status = "error"
        log.error_message = str(e)
        log.completed_at = datetime.utcnow()
        await session.commit()
        raise HTTPException(status_code=502, detail=f"Error de Holded: {e.detail}")


@router.post("/sync/expenses", response_model=SyncResult)
async def sync_expenses(
    session: AsyncSession = Depends(get_db),
    user=Depends(require_admin),
):
    """Sync Holded purchase documents → local cache."""
    holded = _get_holded_client()
    log = HoldedSyncLog(sync_type="expenses", status="in_progress")
    session.add(log)
    await session.flush()

    try:
        expenses = await holded.list_expenses()
        synced = 0

        for exp in expenses:
            holded_id = exp.get("id", "")
            if not holded_id:
                continue

            result = await session.execute(
                select(HoldedExpenseCache).where(HoldedExpenseCache.holded_id == holded_id)
            )
            cached = result.scalar_one_or_none()

            exp_date = _parse_holded_date(exp.get("date"))
            total = float(exp.get("total", 0) or 0)
            subtotal = float(exp.get("subtotal", 0) or 0)
            tax_val = float(exp.get("tax", 0) or 0)
            status = "paid" if exp.get("paid") else "pending"

            if cached:
                cached.description = exp.get("desc", cached.description) or exp.get("contactName", "")
                cached.date = exp_date
                cached.total = total
                cached.subtotal = subtotal
                cached.tax = tax_val
                cached.category = exp.get("tags", [None])[0] if exp.get("tags") else None
                cached.supplier = exp.get("contactName", cached.supplier)
                cached.status = status
                cached.raw_data = exp
                cached.synced_at = datetime.utcnow()
            else:
                session.add(HoldedExpenseCache(
                    holded_id=holded_id,
                    description=exp.get("desc", "") or exp.get("contactName", ""),
                    date=exp_date,
                    total=total,
                    subtotal=subtotal,
                    tax=tax_val,
                    category=exp.get("tags", [None])[0] if exp.get("tags") else None,
                    supplier=exp.get("contactName"),
                    status=status,
                    raw_data=exp,
                ))

            synced += 1

        log.status = "success"
        log.records_synced = synced
        log.completed_at = datetime.utcnow()
        await session.commit()

        return SyncResult(sync_type="expenses", status="success", records_synced=synced)

    except HoldedError as e:
        log.status = "error"
        log.error_message = str(e)
        log.completed_at = datetime.utcnow()
        await session.commit()
        raise HTTPException(status_code=502, detail=f"Error de Holded: {e.detail}")


@router.post("/sync/all")
async def sync_all(
    session: AsyncSession = Depends(get_db),
    user=Depends(require_admin),
):
    """Full sync: contacts → invoices → expenses."""
    results = []
    for sync_fn in [sync_contacts, sync_invoices, sync_expenses]:
        try:
            r = await sync_fn(session=session, user=user)
            results.append(r)
        except HTTPException as e:
            results.append(SyncResult(
                sync_type=sync_fn.__name__.replace("sync_", ""),
                status="error",
                records_synced=0,
                error_message=e.detail,
            ))
    return results


@router.get("/sync/status", response_model=SyncStatusResponse)
async def sync_status(
    session: AsyncSession = Depends(get_db),
    user=Depends(require_admin),
):
    """Last sync status per type."""
    result = {}
    for sync_type in ["contacts", "invoices", "expenses"]:
        q = await session.execute(
            select(HoldedSyncLog)
            .where(HoldedSyncLog.sync_type == sync_type)
            .order_by(desc(HoldedSyncLog.started_at))
            .limit(1)
        )
        log = q.scalar_one_or_none()
        result[sync_type] = log
    return SyncStatusResponse(**result)


@router.get("/sync/logs", response_model=list[SyncLogResponse])
async def sync_logs(
    limit: int = Query(20, le=100),
    session: AsyncSession = Depends(get_db),
    user=Depends(require_admin),
):
    """Recent sync history."""
    q = await session.execute(
        select(HoldedSyncLog).order_by(desc(HoldedSyncLog.started_at)).limit(limit)
    )
    return q.scalars().all()


# ── Data endpoints (read from cache) ──────────────────────


@router.get("/invoices")
async def list_invoices(
    client_id: Optional[int] = Query(None),
    status: Optional[str] = Query(None),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_db),
    user=Depends(require_admin),
):
    q = select(HoldedInvoiceCache).order_by(desc(HoldedInvoiceCache.date))
    if client_id:
        q = q.where(HoldedInvoiceCache.client_id == client_id)
    if status:
        q = q.where(HoldedInvoiceCache.status == status)
    if date_from:
        q = q.where(HoldedInvoiceCache.date >= date_from)
    if date_to:
        q = q.where(HoldedInvoiceCache.date <= date_to)

    total = (await session.execute(select(func.count()).select_from(q.subquery()))).scalar() or 0
    result = await session.execute(q.offset((page - 1) * page_size).limit(page_size))
    return {"items": result.scalars().all(), "total": total, "page": page, "page_size": page_size}


@router.get("/invoices/{holded_id}/pdf")
async def get_invoice_pdf(
    holded_id: str,
    user=Depends(require_admin),
):
    """Download PDF from Holded."""
    holded = _get_holded_client()
    try:
        pdf_bytes = await holded.get_invoice_pdf(holded_id)
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename=factura-{holded_id}.pdf"},
        )
    except HoldedError as e:
        raise HTTPException(status_code=502, detail=f"Error descargando PDF: {e.detail}")


@router.get("/expenses")
async def list_expenses(
    category: Optional[str] = Query(None),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_db),
    user=Depends(require_admin),
):
    q = select(HoldedExpenseCache).order_by(desc(HoldedExpenseCache.date))
    if category:
        q = q.where(HoldedExpenseCache.category == category)
    if date_from:
        q = q.where(HoldedExpenseCache.date >= date_from)
    if date_to:
        q = q.where(HoldedExpenseCache.date <= date_to)

    total = (await session.execute(select(func.count()).select_from(q.subquery()))).scalar() or 0
    result = await session.execute(q.offset((page - 1) * page_size).limit(page_size))
    return {"items": result.scalars().all(), "total": total, "page": page, "page_size": page_size}


@router.get("/dashboard", response_model=HoldedDashboardResponse)
async def holded_dashboard(
    session: AsyncSession = Depends(get_db),
    user=Depends(require_admin),
):
    """Financial summary from Holded cache."""
    try:
        return await _build_holded_dashboard(session)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Error building Holded dashboard: {str(e)}")


async def _build_holded_dashboard(session: AsyncSession) -> HoldedDashboardResponse:
    now = date.today()
    year_start = date(now.year, 1, 1)
    month_start = date(now.year, now.month, 1)

    # This month
    r = await session.execute(
        select(func.coalesce(func.sum(HoldedInvoiceCache.total), 0))
        .where(HoldedInvoiceCache.date >= month_start)
    )
    income_month = float(r.scalar())

    r = await session.execute(
        select(func.coalesce(func.sum(HoldedExpenseCache.total), 0))
        .where(HoldedExpenseCache.date >= month_start)
    )
    expenses_month = float(r.scalar())

    # YTD
    r = await session.execute(
        select(func.coalesce(func.sum(HoldedInvoiceCache.total), 0))
        .where(HoldedInvoiceCache.date >= year_start)
    )
    income_ytd = float(r.scalar())

    r = await session.execute(
        select(func.coalesce(func.sum(HoldedExpenseCache.total), 0))
        .where(HoldedExpenseCache.date >= year_start)
    )
    expenses_ytd = float(r.scalar())

    # Pending invoices
    r = await session.execute(
        select(HoldedInvoiceCache)
        .where(HoldedInvoiceCache.status.in_(["pending", "overdue"]))
        .order_by(HoldedInvoiceCache.date)
    )
    pending_invoices = r.scalars().all()

    # Monthly data (last 6 months)
    monthly_data = []
    for i in range(5, -1, -1):
        m = now.month - i
        y = now.year
        if m <= 0:
            m += 12
            y -= 1
        m_start = date(y, m, 1)
        if m == 12:
            m_end = date(y + 1, 1, 1)
        else:
            m_end = date(y, m + 1, 1)

        r_inc = await session.execute(
            select(func.coalesce(func.sum(HoldedInvoiceCache.total), 0))
            .where(HoldedInvoiceCache.date >= m_start, HoldedInvoiceCache.date < m_end)
        )
        r_exp = await session.execute(
            select(func.coalesce(func.sum(HoldedExpenseCache.total), 0))
            .where(HoldedExpenseCache.date >= m_start, HoldedExpenseCache.date < m_end)
        )
        inc = float(r_inc.scalar())
        exp = float(r_exp.scalar())
        monthly_data.append(MonthlyFinancials(
            month=f"{y}-{m:02d}",
            income=inc,
            expenses=exp,
            profit=inc - exp,
        ))

    return HoldedDashboardResponse(
        income_this_month=income_month,
        expenses_this_month=expenses_month,
        profit_this_month=income_month - expenses_month,
        income_ytd=income_ytd,
        expenses_ytd=expenses_ytd,
        profit_ytd=income_ytd - expenses_ytd,
        pending_invoices=pending_invoices,
        monthly_data=monthly_data,
    )


# ── Config endpoints ───────────────────────────────────────


@router.get("/config", response_model=HoldedConfigResponse)
async def holded_config(
    session: AsyncSession = Depends(get_db),
    user=Depends(require_admin),
):
    result = {}
    for sync_type in ["contacts", "invoices", "expenses"]:
        q = await session.execute(
            select(HoldedSyncLog)
            .where(HoldedSyncLog.sync_type == sync_type)
            .order_by(desc(HoldedSyncLog.started_at))
            .limit(1)
        )
        result[f"last_sync_{sync_type}"] = q.scalar_one_or_none()

    # Derive connection health from most recent sync across all types
    last_syncs = [v for v in result.values() if v is not None]
    healthy = bool(settings.HOLDED_API_KEY) and any(
        s.status == "success" for s in last_syncs
    ) if last_syncs else False

    return HoldedConfigResponse(
        api_key_configured=bool(settings.HOLDED_API_KEY),
        connection_healthy=healthy,
        **result,
    )


@router.post("/test-connection", response_model=TestConnectionResponse)
async def test_connection(
    user=Depends(require_admin),
):
    if not settings.HOLDED_API_KEY:
        return TestConnectionResponse(success=False, message="HOLDED_API_KEY no configurada en el servidor")
    holded = HoldedClient(settings.HOLDED_API_KEY)
    try:
        ok = await holded.test_connection()
        if ok:
            return TestConnectionResponse(success=True, message="Conexion exitosa con Holded")
        return TestConnectionResponse(success=False, message="No se pudo conectar con Holded")
    except Exception as e:
        return TestConnectionResponse(success=False, message=f"Error: {str(e)}")


# ── Client-level invoice lookup ────────────────────────────


@router.get("/clients/{client_id}/invoices", response_model=list[HoldedInvoiceResponse])
async def client_invoices(
    client_id: int,
    session: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Invoices for a specific client (by holded link)."""
    r = await session.execute(
        select(HoldedInvoiceCache)
        .where(HoldedInvoiceCache.client_id == client_id)
        .order_by(desc(HoldedInvoiceCache.date))
    )
    return r.scalars().all()


# ── Helpers ────────────────────────────────────────────────

def _parse_holded_date(val) -> Optional[date]:
    """Parse Holded date field (unix timestamp in seconds or ISO string)."""
    if not val:
        return None
    try:
        if isinstance(val, (int, float)):
            return datetime.utcfromtimestamp(val).date()
        if isinstance(val, str):
            return datetime.fromisoformat(val.replace("Z", "+00:00")).date()
    except (ValueError, OSError):
        return None
    return None
