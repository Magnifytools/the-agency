"""Proposals router — thin aggregator that includes sub-routers.

Split into:
  - proposals_crud.py    — CRUD, status, duplicate, convert, AI generation
  - proposals_pricing.py — investment model
  - proposals_pdf.py     — PDF/HTML generation, email sending
"""
from fastapi import APIRouter

from backend.api.routes.proposals_crud import router as crud_router
from backend.api.routes.proposals_pricing import router as pricing_router
from backend.api.routes.proposals_pdf import router as pdf_router

# Each sub-router already carries prefix="/api/proposals" and tags=["proposals"].
# This aggregator router has NO prefix — it just groups them for main.py's
# single `app.include_router(proposals.router)` call.
router = APIRouter()

router.include_router(crud_router)
router.include_router(pricing_router)
router.include_router(pdf_router)
