from __future__ import annotations
from typing import Optional, Any
from datetime import datetime
from pydantic import BaseModel


class CsvPreviewRequest(BaseModel):
    content: str
    delimiter: str = ","


class CsvPreviewResponse(BaseModel):
    headers: list[str]
    rows: list[list[str]]
    total_rows: int
    detected_delimiter: str


class CsvImportRequest(BaseModel):
    content: str
    target: str = "expenses"  # expenses, income
    mapping: dict[str, str]  # csv_column -> db_field
    delimiter: str = ","


class CsvImportResponse(BaseModel):
    records_processed: int
    records_imported: int
    records_skipped: int
    errors: list[str]


class CsvMappingCreate(BaseModel):
    name: str
    target: str = "expenses"
    mapping: dict[str, str]
    delimiter: str = ","


class CsvMappingResponse(BaseModel):
    id: int
    name: str
    target: str
    mapping: Any
    delimiter: str
    created_at: datetime

    model_config = {"from_attributes": True}


class SyncLogResponse(BaseModel):
    id: int
    source: str
    file_name: str
    records_processed: int
    records_imported: int
    records_skipped: int
    errors: str
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}
