from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.database import get_db
from backend.db.models import Income, Expense, SyncLog, CsvMapping, User
from backend.schemas.sync import (
    CsvPreviewRequest, CsvPreviewResponse, CsvImportRequest, CsvImportResponse,
    CsvMappingCreate, CsvMappingResponse, SyncLogResponse,
)
from backend.services.csv_service import process_csv_preview, parse_csv, parse_date, parse_amount
from backend.api.deps import require_module

router = APIRouter(prefix="/api/finance/sync", tags=["finance-import"])


@router.post("/preview", response_model=CsvPreviewResponse)
async def preview_csv(
    body: CsvPreviewRequest,
    _user: User = Depends(require_module("finance_import")),
):
    result = process_csv_preview(body.content)
    return CsvPreviewResponse(**result)


@router.post("/import", response_model=CsvImportResponse)
async def import_csv(
    body: CsvImportRequest,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_module("finance_import")),
):
    rows = parse_csv(body.content, body.delimiter)
    imported = 0
    skipped = 0
    errors: list[str] = []

    for i, row in enumerate(rows, 1):
        try:
            # Map CSV columns to DB fields
            date_val = parse_date(row.get(body.mapping.get("date", ""), ""))
            if not date_val:
                errors.append(f"Fila {i}: fecha invalida")
                skipped += 1
                continue

            amount_val = parse_amount(row.get(body.mapping.get("amount", ""), "0"))
            if amount_val is None:
                errors.append(f"Fila {i}: importe invalido")
                skipped += 1
                continue

            description = row.get(body.mapping.get("description", ""), "Sin descripcion")

            if body.target == "expenses":
                item = Expense(
                    date=date.fromisoformat(date_val),
                    description=description,
                    amount=abs(amount_val),
                )
            else:
                item = Income(
                    date=date.fromisoformat(date_val),
                    description=description,
                    amount=abs(amount_val),
                )
            db.add(item)
            imported += 1
        except Exception as e:
            errors.append(f"Fila {i}: {str(e)}")
            skipped += 1

    # Log the sync
    log = SyncLog(
        source="csv",
        file_name="import",
        records_processed=len(rows),
        records_imported=imported,
        records_skipped=skipped,
        errors="; ".join(errors[:20]),
        status="completado" if not errors else "parcial",
    )
    db.add(log)
    await db.commit()

    return CsvImportResponse(
        records_processed=len(rows),
        records_imported=imported,
        records_skipped=skipped,
        errors=errors[:20],
    )


@router.get("/mappings", response_model=list[CsvMappingResponse])
async def list_mappings(
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_module("finance_import")),
):
    r = await db.execute(select(CsvMapping).order_by(CsvMapping.created_at.desc()))
    return [CsvMappingResponse.model_validate(m) for m in r.scalars().all()]


@router.post("/mappings", response_model=CsvMappingResponse, status_code=status.HTTP_201_CREATED)
async def create_mapping(
    data: CsvMappingCreate,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_module("finance_import")),
):
    m = CsvMapping(**data.model_dump())
    db.add(m)
    await db.commit()
    await db.refresh(m)
    return CsvMappingResponse.model_validate(m)


@router.delete("/mappings/{mapping_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_mapping(
    mapping_id: int,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_module("finance_import")),
):
    r = await db.execute(select(CsvMapping).where(CsvMapping.id == mapping_id))
    m = r.scalars().first()
    if not m:
        raise HTTPException(status_code=404, detail="Mapping no encontrado")
    await db.delete(m)
    await db.commit()


@router.get("/logs", response_model=list[SyncLogResponse])
async def list_logs(
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_module("finance_import")),
):
    r = await db.execute(select(SyncLog).order_by(SyncLog.created_at.desc()).limit(50))
    return [SyncLogResponse.model_validate(l) for l in r.scalars().all()]
