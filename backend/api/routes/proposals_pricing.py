"""Proposals pricing / investment model endpoints."""
from __future__ import annotations
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.attributes import flag_modified

from backend.db.database import get_db
from backend.db.models import Proposal, User
from backend.api.deps import require_module
from backend.schemas.proposal import ProposalResponse, InvestmentModelInput
from backend.api.utils.db_helpers import safe_refresh
from backend.api.routes.proposals_crud import _to_response

router = APIRouter(prefix="/api/proposals", tags=["proposals"])
logger = logging.getLogger(__name__)


@router.post("/{proposal_id}/save-investment", response_model=ProposalResponse)
async def save_investment_model(
    proposal_id: int,
    body: InvestmentModelInput,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_module("proposals")),
):
    """Save calculated investment model to proposal's generated_content."""
    result = await db.execute(
        select(Proposal).where(Proposal.id == proposal_id)
        .options(selectinload(Proposal.client), selectinload(Proposal.lead), selectinload(Proposal.created_by_user))
    )
    prop = result.scalar_one_or_none()
    if not prop:
        raise HTTPException(status_code=404, detail="Propuesta no encontrada")

    content = prop.generated_content or {}
    content["investment_model"] = body.model_dump()
    prop.generated_content = content
    flag_modified(prop, "generated_content")
    await db.commit()
    await safe_refresh(db, prop, log_context="proposals")
    return _to_response(prop)
