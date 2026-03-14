"""Data assistant API — natural language queries over agency data."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.database import get_db
from backend.api.deps import get_current_user, require_admin
from backend.db.models import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/assistant", tags=["assistant"])


class AskRequest(BaseModel):
    question: str = Field(..., min_length=3, max_length=500)


@router.post("/ask")
async def ask(
    body: AskRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Ask a natural language question about agency data. Admin only."""
    try:
        from backend.services.data_assistant import ask_assistant
        result = await ask_assistant(body.question, db)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("Assistant error: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Error procesando la pregunta")
