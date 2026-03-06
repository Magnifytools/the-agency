"""Core Update analysis endpoint — keyword shift analyzer."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.api.deps import get_current_user
from backend.db.models import User
from backend.services.core_update_service import run_core_update_analysis

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/engine", tags=["core-updates"])


class CoreUpdateAnalyzeRequest(BaseModel):
    period_pre_start: str  # "YYYY-MM-DD"
    period_pre_end: str
    period_post_start: str
    period_post_end: str
    top_n: int = 1000
    metric: str = "clicks"  # "clicks" | "impressions"


@router.post("/projects/{project_id}/core-updates/analyze")
async def analyze_core_update(
    project_id: int,
    body: CoreUpdateAnalyzeRequest,
    current_user: User = Depends(get_current_user),
):
    try:
        result = await run_core_update_analysis(
            project_id=project_id,
            pre_start=body.period_pre_start,
            pre_end=body.period_pre_end,
            post_start=body.period_post_start,
            post_end=body.period_post_end,
            top_n=body.top_n,
            metric=body.metric,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        logger.exception("Error en análisis de core update para proyecto %s", project_id)
        raise HTTPException(status_code=500, detail="Error interno en análisis de core update")
