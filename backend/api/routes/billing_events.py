from __future__ import annotations

from datetime import date, timedelta
from dateutil.relativedelta import relativedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.database import get_db
from backend.db.models import User, Client, BillingEvent, BillingEventType, BillingCycle
from backend.schemas.billing_event import BillingEventCreate, BillingEventResponse, BillingStatusResponse
from backend.api.deps import get_current_user, require_module, get_client_or_404

router = APIRouter(prefix="/api/clients/{client_id}/billing", tags=["billing-events"])


_CYCLE_DELTAS = {
    BillingCycle.monthly: relativedelta(months=1),
    BillingCycle.bimonthly: relativedelta(months=2),
    BillingCycle.quarterly: relativedelta(months=3),
    BillingCycle.annual: relativedelta(years=1),
}


def _calc_next_invoice_date(current: date, cycle: BillingCycle) -> date:
    """Calculate the next invoice date based on billing cycle."""
    delta = _CYCLE_DELTAS.get(cycle)
    return current + delta if delta else current


@router.get("", response_model=list[BillingEventResponse])
async def list_billing_events(
    client_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_module("clients")),
):
    result = await db.execute(
        select(BillingEvent)
        .where(BillingEvent.client_id == client_id)
        .order_by(BillingEvent.event_date.desc())
        .limit(50)
    )
    return result.scalars().all()


@router.post("", response_model=BillingEventResponse, status_code=201)
async def create_billing_event(
    client_id: int,
    body: BillingEventCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_module("clients", write=True)),
):
    await get_client_or_404(client_id, db)
    event = BillingEvent(client_id=client_id, **body.model_dump())
    db.add(event)
    await db.commit()
    await db.refresh(event)
    return event


@router.get("/status", response_model=BillingStatusResponse)
async def billing_status(
    client_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_module("clients")),
):
    client = await get_client_or_404(client_id, db)
    today = date.today()
    days_until = None
    is_overdue = False
    if client.next_invoice_date:
        delta = (client.next_invoice_date - today).days
        days_until = delta
        is_overdue = delta < 0

    # Last payment
    result = await db.execute(
        select(BillingEvent)
        .where(
            BillingEvent.client_id == client_id,
            BillingEvent.event_type == BillingEventType.payment_received,
        )
        .order_by(BillingEvent.event_date.desc())
        .limit(1)
    )
    last_payment = result.scalar_one_or_none()

    return {
        "billing_cycle": client.billing_cycle.value if client.billing_cycle else None,
        "billing_day": client.billing_day,
        "next_invoice_date": client.next_invoice_date.isoformat() if client.next_invoice_date else None,
        "last_invoiced_date": client.last_invoiced_date.isoformat() if client.last_invoiced_date else None,
        "days_until_invoice": days_until,
        "is_overdue": is_overdue,
        "monthly_fee": client.monthly_fee,
        "last_payment_date": last_payment.event_date.isoformat() if last_payment else None,
        "last_payment_amount": last_payment.amount if last_payment else None,
    }


@router.post("/mark-invoiced", response_model=BillingEventResponse)
async def mark_invoiced(
    client_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_module("clients", write=True)),
):
    client = await get_client_or_404(client_id, db)
    today = date.today()

    # Create billing event
    event = BillingEvent(
        client_id=client_id,
        event_type=BillingEventType.invoice_sent,
        amount=client.monthly_fee,
        event_date=today,
    )
    db.add(event)

    # Update client
    client.last_invoiced_date = today
    if client.billing_cycle and client.billing_cycle != BillingCycle.one_time:
        billing_day = client.billing_day or today.day
        base_date = today.replace(day=min(billing_day, 28))
        client.next_invoice_date = _calc_next_invoice_date(base_date, client.billing_cycle)

    await db.commit()
    await db.refresh(event)
    return event


@router.post("/mark-paid", response_model=BillingEventResponse)
async def mark_paid(
    client_id: int,
    amount: float | None = None,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_module("clients", write=True)),
):
    client = await get_client_or_404(client_id, db)
    event = BillingEvent(
        client_id=client_id,
        event_type=BillingEventType.payment_received,
        amount=amount or client.monthly_fee,
        event_date=date.today(),
    )
    db.add(event)
    await db.commit()
    await db.refresh(event)
    return event
