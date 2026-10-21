from __future__ import annotations
from typing import Optional

from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator
from backend.db.models import ContractType, ClientStatus
from backend.services.seo_control import clean_brand_terms, clean_page_groups
from backend.services.seo_traffic import SeoTrend, seo_traffic


class ClientCreate(BaseModel):
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    company: Optional[str] = None
    website: Optional[str] = None
    contract_type: ContractType = ContractType.monthly
    monthly_budget: Optional[float] = Field(None, ge=0)
    status: ClientStatus = ClientStatus.active
    notes: Optional[str] = None
    is_internal: bool = False
    intermediary_name: Optional[str] = None
    is_intermediary_deal: bool = False
    vat_number: Optional[str] = None
    ga4_property_id: Optional[str] = None
    gsc_url: Optional[str] = None
    # Revenue intelligence
    context: Optional[str] = None


class ClientUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    company: Optional[str] = None
    website: Optional[str] = None
    contract_type: Optional[ContractType] = None
    monthly_budget: Optional[float] = Field(None, ge=0)
    status: Optional[ClientStatus] = None
    notes: Optional[str] = None
    is_internal: Optional[bool] = None
    vat_number: Optional[str] = None
    ga4_property_id: Optional[str] = None
    gsc_url: Optional[str] = None
    engine_project_id: Optional[int] = None
    vigil_slug: Optional[str] = None
    intermediary_name: Optional[str] = None
    is_intermediary_deal: Optional[bool] = None
    # Revenue intelligence
    context: Optional[str] = None
    slack_template: Optional[dict] = None
    # Control SEO: búsquedas que cuentan como "de marca".
    brand_terms: Optional[list[str]] = None

    @field_validator("brand_terms", mode="before")
    @classmethod
    def _brand_terms(cls, value):
        # null = sin términos (la columna no admite NULL).
        if value is not None and not isinstance(value, list):
            raise ValueError("Los términos de marca son una lista")
        return clean_brand_terms(value)

    # Control SEO: grupos de URL [{name, rules: [{type, value}]}].
    seo_page_groups: Optional[list[dict]] = None

    @field_validator("seo_page_groups", mode="before")
    @classmethod
    def _page_groups(cls, value):
        # null = sin grupos (la columna no admite NULL).
        return clean_page_groups(value)


class ClientResponse(BaseModel):
    id: int
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    company: Optional[str] = None
    website: Optional[str] = None
    contract_type: ContractType
    monthly_budget: Optional[float] = None
    status: ClientStatus
    notes: Optional[str] = None
    ga4_property_id: Optional[str] = None
    gsc_url: Optional[str] = None
    brand_terms: list[str] = Field(default_factory=list)
    seo_page_groups: list[dict] = Field(default_factory=list)
    engine_project_id: Optional[int] = None
    vigil_slug: Optional[str] = None
    engine_content_count: Optional[int] = None
    engine_keyword_count: Optional[int] = None
    engine_avg_position: Optional[float] = None
    engine_clicks_30d: Optional[int] = None
    engine_impressions_30d: Optional[int] = None
    engine_metrics_synced_at: Optional[datetime] = None
    engine_summary_data: Optional[dict] = None
    engine_alerts_data: Optional[dict] = None
    # Revenue intelligence
    is_internal: bool = False
    intermediary_name: Optional[str] = None
    is_intermediary_deal: bool = False
    vat_number: Optional[str] = None
    context: Optional[str] = None
    slack_template: Optional[dict] = None
    onboarding_intelligence: Optional[dict] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

    @field_validator("brand_terms", mode="before")
    @classmethod
    def _brand_terms_list(cls, value):
        return value or []

    @field_validator("seo_page_groups", mode="before")
    @classmethod
    def _page_groups_list(cls, value):
        return value or []

    # Semáforo SEO: derivado del summary de Engine, sin almacenamiento propio.
    @computed_field
    @property
    def seo_clicks_change_pct(self) -> Optional[float]:
        traffic = seo_traffic(self.engine_summary_data)
        return traffic.clicks_change_pct if traffic else None

    @computed_field
    @property
    def seo_impressions_change_pct(self) -> Optional[float]:
        traffic = seo_traffic(self.engine_summary_data)
        return traffic.impressions_change_pct if traffic else None

    @computed_field
    @property
    def seo_trend(self) -> Optional[SeoTrend]:
        traffic = seo_traffic(self.engine_summary_data)
        return traffic.trend if traffic else None


class ClientDocumentResponse(BaseModel):
    id: int
    client_id: int
    name: str
    description: Optional[str] = None
    mime_type: str
    size_bytes: int
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)
