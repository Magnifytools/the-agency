from typing import Any, Optional
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from jinja2 import Environment, BaseLoader

from backend.db.database import get_db
from backend.db.models import Proposal, Client, Project, User, ProposalStatus
from backend.api.deps import get_current_user
from backend.schemas.proposal import ProposalCreate, ProposalUpdate, ProposalResponse

router = APIRouter(prefix="/api/proposals", tags=["proposals"])

def _to_response(prop: Proposal) -> dict[str, Any]:
    return {
        "id": prop.id,
        "title": prop.title,
        "status": prop.status.value,
        "budget": prop.budget,
        "scope": prop.scope,
        "valid_until": prop.valid_until,
        "client_id": prop.client_id,
        "project_id": prop.project_id,
        "created_at": prop.created_at,
        "updated_at": prop.updated_at,
        "client_name": prop.client.name if prop.client else None,
        "project_name": prop.project.name if prop.project else None,
    }

@router.get("", response_model=list[ProposalResponse])
async def list_proposals(
    client_id: Optional[int] = None,
    status_filter: Optional[ProposalStatus] = None,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    query = select(Proposal)
    
    if client_id:
        query = query.where(Proposal.client_id == client_id)
    if status_filter:
        query = query.where(Proposal.status == status_filter)
        
    query = query.order_by(Proposal.created_at.desc())
    
    result = await db.execute(query)
    proposals = result.scalars().all()
    return [_to_response(p) for p in proposals]


@router.post("", response_model=ProposalResponse)
async def create_proposal(
    data: ProposalCreate,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    # Verify client exists
    client = await db.execute(select(Client).where(Client.id == data.client_id))
    if not client.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Client not found")

    new_prop = Proposal(**data.model_dump())
    db.add(new_prop)
    await db.commit()
    await db.refresh(new_prop)
    
    # Reload with relations
    stmt = select(Proposal).where(Proposal.id == new_prop.id)
    result = await db.execute(stmt)
    full_prop = result.scalar_one()
    return _to_response(full_prop)


@router.get("/{proposal_id}", response_model=ProposalResponse)
async def get_proposal(
    proposal_id: int,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    result = await db.execute(select(Proposal).where(Proposal.id == proposal_id))
    prop = result.scalar_one_or_none()
    
    if not prop:
        raise HTTPException(status_code=404, detail="Proposal not found")
        
    return _to_response(prop)


@router.put("/{proposal_id}", response_model=ProposalResponse)
async def update_proposal(
    proposal_id: int,
    data: ProposalUpdate,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    result = await db.execute(select(Proposal).where(Proposal.id == proposal_id))
    prop = result.scalar_one_or_none()
    
    if not prop:
        raise HTTPException(status_code=404, detail="Proposal not found")

    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(prop, key, value)
        
    await db.commit()
    await db.refresh(prop)
    
    stmt = select(Proposal).where(Proposal.id == prop.id)
    res = await db.execute(stmt)
    return _to_response(res.scalar_one())


@router.delete("/{proposal_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_proposal(
    proposal_id: int,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    result = await db.execute(select(Proposal).where(Proposal.id == proposal_id))
    prop = result.scalar_one_or_none()
    
    if not prop:
        raise HTTPException(status_code=404, detail="Proposal not found")
        
    await db.delete(prop)
    await db.commit()


# A basic HTML template for WeasyPrint
PDF_HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>{{ proposal.title }}</title>
    <style>
        body { font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif; color: #333; line-height: 1.6; margin: 0; padding: 40px; }
        .header { border-bottom: 2px solid #000; padding-bottom: 20px; margin-bottom: 40px; }
        .header h1 { margin: 0; font-size: 28px; }
        .header p { margin: 5px 0 0; color: #666; font-size: 14px; }
        .meta { display: flex; justify-content: space-between; margin-bottom: 40px; }
        .meta-col { flex: 1; }
        .meta-label { font-size: 12px; text-transform: uppercase; color: #888; font-weight: bold; }
        .meta-value { font-size: 16px; font-weight: 500; margin-top: 5px; }
        .content { margin-bottom: 50px; }
        .content h2 { font-size: 20px; border-bottom: 1px solid #ddd; padding-bottom: 10px; margin-bottom: 20px; }
        .budget { background: #f9f9f9; padding: 20px; border-radius: 8px; text-align: center; }
        .budget-amount { font-size: 32px; font-weight: bold; color: #222; }
        .footer { border-top: 1px solid #ddd; padding-top: 20px; text-align: center; font-size: 12px; color: #888; }
    </style>
</head>
<body>
    <div class="header">
        <h1>Propuesta Comercial</h1>
        <p>{{ proposal.title }}</p>
    </div>
    
    <table width="100%" style="margin-bottom: 40px">
        <tr>
            <td width="50%">
                <div class="meta-label">PREPARADO PARA</div>
                <div class="meta-value">{{ client_name }}</div>
            </td>
            <td width="50%" style="text-align: right">
                <div class="meta-label">FECHA</div>
                <div class="meta-value">{{ date.strftime('%d/%m/%Y') }}</div>
            </td>
        </tr>
    </table>

    <div class="content">
        <h2>Alcance del Servicio</h2>
        <div style="white-space: pre-wrap;">{{ proposal.scope or 'No se ha detallado un alcance.' }}</div>
    </div>

    {% if proposal.budget %}
    <div class="budget">
        <div class="meta-label">INVERSIÓN ESTIMADA</div>
        <div class="budget-amount">{{ "{:,.2f}".format(proposal.budget).replace(',', '.') }} €</div>
        <p style="font-size: 12px; color: #666; margin-top: 10px;">Impuestos no incluidos</p>
    </div>
    {% endif %}

    <div class="footer">
        <p>Validez de la oferta: {{ validity_days }} días</p>
    </div>
</body>
</html>
"""

@router.get("/{proposal_id}/pdf")
async def generate_proposal_pdf(
    proposal_id: int,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    try:
        from weasyprint import HTML
    except ImportError:
        raise HTTPException(status_code=500, detail="WeasyPrint is not installed or configured correctly.")

    result = await db.execute(select(Proposal).where(Proposal.id == proposal_id))
    prop = result.scalar_one_or_none()
    
    if not prop:
        raise HTTPException(status_code=404, detail="Proposal not found")

    env = Environment(loader=BaseLoader())
    template = env.from_string(PDF_HTML_TEMPLATE)
    
    validity_days = 30
    if prop.valid_until:
        validity_days = max(1, (prop.valid_until - datetime.utcnow()).days)
        
    html_content = template.render(
        proposal=prop,
        client_name=prop.client.name if prop.client else "Cliente",
        date=prop.created_at or datetime.utcnow(),
        validity_days=validity_days
    )
    
    pdf_bytes = HTML(string=html_content).write_pdf()
    
    # Return as standard PDF download
    filename = f"Propuesta_{prop.title.replace(' ', '_')}.pdf"
    
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"'
        }
    )
