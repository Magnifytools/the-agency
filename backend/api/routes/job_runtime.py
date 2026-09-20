"""Administrative runtime status; no execution or configuration mutations."""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import require_admin
from backend.db.database import get_db
from backend.db.models import User
from backend.services.job_runtime_status import list_job_status


router = APIRouter(prefix="/api/admin/job-runtime", tags=["admin-runtime"])


@router.get("")
async def job_runtime_status(db: AsyncSession = Depends(get_db), _user: User = Depends(require_admin)):
    return await list_job_status(db)
