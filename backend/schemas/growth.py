from typing import Optional, List
from pydantic import BaseModel
from datetime import datetime
from db.models import GrowthFunnelStage, GrowthStatus

class GrowthIdeaBase(BaseModel):
    title: str
    description: Optional[str] = None
    funnel_stage: GrowthFunnelStage = GrowthFunnelStage.other
    target_kpi: Optional[str] = None
    status: GrowthStatus = GrowthStatus.idea
    impact: int = 5
    confidence: int = 5
    ease: int = 5
    experiment_start_date: Optional[datetime] = None
    experiment_end_date: Optional[datetime] = None
    results_notes: Optional[str] = None
    is_successful: Optional[bool] = None
    project_id: Optional[int] = None
    task_id: Optional[int] = None

class GrowthIdeaCreate(GrowthIdeaBase):
    pass

class GrowthIdeaUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    funnel_stage: Optional[GrowthFunnelStage] = None
    target_kpi: Optional[str] = None
    status: Optional[GrowthStatus] = None
    impact: Optional[int] = None
    confidence: Optional[int] = None
    ease: Optional[int] = None
    experiment_start_date: Optional[datetime] = None
    experiment_end_date: Optional[datetime] = None
    results_notes: Optional[str] = None
    is_successful: Optional[bool] = None
    project_id: Optional[int] = None
    task_id: Optional[int] = None

class GrowthIdeaResponse(GrowthIdeaBase):
    id: int
    ice_score: int
    created_at: datetime
    updated_at: datetime
    
    project_name: Optional[str] = None
    task_title: Optional[str] = None

    model_config = {"from_attributes": True}
