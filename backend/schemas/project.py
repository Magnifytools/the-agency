from __future__ import annotations
from typing import Optional

from datetime import datetime
from pydantic import BaseModel


# --- Project Phase Schemas ---

class ProjectPhaseCreate(BaseModel):
    name: str
    description: Optional[str] = None
    order_index: int = 0
    start_date: Optional[datetime] = None
    due_date: Optional[datetime] = None


class ProjectPhaseUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    order_index: Optional[int] = None
    start_date: Optional[datetime] = None
    due_date: Optional[datetime] = None
    status: Optional[str] = None


class ProjectPhaseResponse(BaseModel):
    id: int
    name: str
    description: Optional[str]
    order_index: int
    start_date: Optional[datetime]
    due_date: Optional[datetime]
    completed_at: Optional[datetime]
    status: str
    project_id: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# --- Project Schemas ---

class ProjectCreate(BaseModel):
    name: str
    description: Optional[str] = None
    project_type: Optional[str] = None
    start_date: Optional[datetime] = None
    target_end_date: Optional[datetime] = None
    budget_hours: Optional[float] = None
    budget_amount: Optional[float] = None
    gsc_url: Optional[str] = None
    ga4_property_id: Optional[str] = None
    client_id: int


class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    project_type: Optional[str] = None
    start_date: Optional[datetime] = None
    target_end_date: Optional[datetime] = None
    actual_end_date: Optional[datetime] = None
    status: Optional[str] = None
    progress_percent: Optional[int] = None
    budget_hours: Optional[float] = None
    budget_amount: Optional[float] = None
    gsc_url: Optional[str] = None
    ga4_property_id: Optional[str] = None


class ProjectResponse(BaseModel):
    id: int
    name: str
    description: Optional[str]
    project_type: Optional[str]
    start_date: Optional[datetime]
    target_end_date: Optional[datetime]
    actual_end_date: Optional[datetime]
    status: str
    progress_percent: int
    budget_hours: Optional[float]
    budget_amount: Optional[float]
    gsc_url: Optional[str] = None
    ga4_property_id: Optional[str] = None
    client_id: int
    client_name: Optional[str] = None
    phases: list[ProjectPhaseResponse] = []
    task_count: int = 0
    completed_task_count: int = 0
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ProjectListResponse(BaseModel):
    id: int
    name: str
    project_type: Optional[str]
    start_date: Optional[datetime]
    target_end_date: Optional[datetime]
    status: str
    progress_percent: int
    gsc_url: Optional[str] = None
    ga4_property_id: Optional[str] = None
    client_id: int
    client_name: Optional[str] = None
    phase_count: int = 0
    task_count: int = 0
    completed_task_count: int = 0

    model_config = {"from_attributes": True}


# --- Project Templates ---

PROJECT_TEMPLATES = {
    "seo_audit": {
        "name": "Auditoría SEO",
        "phases": [
            {"name": "Análisis técnico", "default_days": 5},
            {"name": "Análisis de contenido", "default_days": 5},
            {"name": "Análisis de enlaces", "default_days": 3},
            {"name": "Informe y recomendaciones", "default_days": 3},
        ],
        "default_tasks": [
            {"phase": 0, "title": "Crawl con Screaming Frog", "minutes": 120},
            {"phase": 0, "title": "Revisar Core Web Vitals", "minutes": 60},
            {"phase": 0, "title": "Analizar estructura de URLs", "minutes": 90},
            {"phase": 1, "title": "Análisis de thin content", "minutes": 120},
            {"phase": 1, "title": "Revisar meta tags", "minutes": 60},
            {"phase": 1, "title": "Evaluar keyword mapping", "minutes": 90},
            {"phase": 2, "title": "Análisis de backlinks", "minutes": 120},
            {"phase": 2, "title": "Identificar enlaces tóxicos", "minutes": 60},
            {"phase": 3, "title": "Redactar informe ejecutivo", "minutes": 180},
            {"phase": 3, "title": "Priorizar recomendaciones", "minutes": 60},
        ],
    },
    "content_strategy": {
        "name": "Estrategia de Contenido",
        "phases": [
            {"name": "Research y análisis", "default_days": 5},
            {"name": "Planificación editorial", "default_days": 3},
            {"name": "Creación de contenido", "default_days": 10},
            {"name": "Publicación y seguimiento", "default_days": 5},
        ],
        "default_tasks": [
            {"phase": 0, "title": "Keyword research", "minutes": 180},
            {"phase": 0, "title": "Análisis de competencia", "minutes": 120},
            {"phase": 1, "title": "Crear calendario editorial", "minutes": 90},
            {"phase": 1, "title": "Definir pillar pages", "minutes": 60},
            {"phase": 2, "title": "Redactar contenidos", "minutes": 480},
            {"phase": 3, "title": "Publicar y optimizar", "minutes": 120},
        ],
    },
    "linkbuilding": {
        "name": "Campaña de Link Building",
        "phases": [
            {"name": "Prospección", "default_days": 5},
            {"name": "Outreach", "default_days": 10},
            {"name": "Seguimiento", "default_days": 10},
            {"name": "Reporting", "default_days": 2},
        ],
        "default_tasks": [
            {"phase": 0, "title": "Identificar sitios objetivo", "minutes": 180},
            {"phase": 0, "title": "Cualificar prospectos", "minutes": 120},
            {"phase": 1, "title": "Preparar templates de email", "minutes": 60},
            {"phase": 1, "title": "Enviar outreach inicial", "minutes": 180},
            {"phase": 2, "title": "Follow-up emails", "minutes": 120},
            {"phase": 2, "title": "Negociar colaboraciones", "minutes": 90},
            {"phase": 3, "title": "Reportar enlaces conseguidos", "minutes": 60},
        ],
    },
    "technical_seo": {
        "name": "SEO Técnico",
        "phases": [
            {"name": "Diagnóstico", "default_days": 3},
            {"name": "Implementación", "default_days": 10},
            {"name": "Validación", "default_days": 3},
        ],
        "default_tasks": [
            {"phase": 0, "title": "Auditar indexación", "minutes": 90},
            {"phase": 0, "title": "Revisar robots.txt y sitemap", "minutes": 60},
            {"phase": 1, "title": "Corregir errores de crawl", "minutes": 180},
            {"phase": 1, "title": "Optimizar velocidad de carga", "minutes": 240},
            {"phase": 1, "title": "Implementar datos estructurados", "minutes": 120},
            {"phase": 2, "title": "Validar cambios en GSC", "minutes": 60},
            {"phase": 2, "title": "Monitorizar impacto", "minutes": 60},
        ],
    },
}
