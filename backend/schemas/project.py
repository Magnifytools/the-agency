from __future__ import annotations

from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel, field_validator

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
    is_recurring: bool = False
    requires_task_review: bool = False
    start_date: Optional[datetime] = None
    target_end_date: Optional[datetime] = None
    budget_hours: Optional[float] = None
    weekly_hours_budget: Optional[float] = None
    monthly_hours_budget: Optional[float] = None
    budget_amount: Optional[float] = None
    gsc_url: Optional[str] = None
    ga4_property_id: Optional[str] = None
    pricing_model: Optional[str] = None  # monthly, per_piece, hourly, project
    monthly_fee: Optional[float] = None
    unit_price: Optional[float] = None
    unit_label: Optional[str] = None
    scope: Optional[str] = None
    client_id: int
    owner_id: Optional[int] = None


class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    project_type: Optional[str] = None
    is_recurring: Optional[bool] = None
    requires_task_review: Optional[bool] = None
    start_date: Optional[datetime] = None
    target_end_date: Optional[datetime] = None
    actual_end_date: Optional[datetime] = None
    status: Optional[str] = None
    progress_percent: Optional[int] = None
    budget_hours: Optional[float] = None
    weekly_hours_budget: Optional[float] = None
    monthly_hours_budget: Optional[float] = None
    budget_amount: Optional[float] = None
    gsc_url: Optional[str] = None
    ga4_property_id: Optional[str] = None
    pricing_model: Optional[str] = None
    monthly_fee: Optional[float] = None
    unit_price: Optional[float] = None
    unit_label: Optional[str] = None
    scope: Optional[str] = None
    billing_day: Optional[int] = None
    billing_amount: Optional[float] = None
    next_billing_date: Optional[date] = None
    owner_id: Optional[int] = None

    @field_validator("status", mode="before")
    @classmethod
    def status_cannot_be_null(cls, value):
        if value is None:
            raise ValueError("El estado no puede ser nulo")
        return value


class ProjectResponse(BaseModel):
    id: int
    name: str
    description: Optional[str]
    project_type: Optional[str]
    is_recurring: bool = False
    requires_task_review: bool = False
    start_date: Optional[datetime]
    target_end_date: Optional[datetime]
    actual_end_date: Optional[datetime]
    status: str
    progress_percent: Optional[int]
    budget_hours: Optional[float]
    weekly_hours_budget: Optional[float] = None
    monthly_hours_budget: Optional[float] = None
    budget_amount: Optional[float]
    gsc_url: Optional[str] = None
    ga4_property_id: Optional[str] = None
    pricing_model: Optional[str] = None
    monthly_fee: Optional[float] = None
    unit_price: Optional[float] = None
    unit_label: Optional[str] = None
    scope: Optional[str] = None
    billing_day: Optional[int] = None
    billing_amount: Optional[float] = None
    next_billing_date: Optional[date] = None
    last_billed_date: Optional[date] = None
    client_id: int
    client_name: Optional[str] = None
    owner_id: Optional[int] = None
    owner_name: Optional[str] = None
    phases: list[ProjectPhaseResponse] = []
    task_count: Optional[int] = None
    completed_task_count: Optional[int] = None
    hours_used: Optional[float] = None
    hours_used_week: Optional[float] = None
    hours_used_month: Optional[float] = None
    # Techos efectivos: caen a budget_hours en retainers mensuales si no hay techo explícito
    effective_weekly_hours_budget: Optional[float] = None
    effective_monthly_hours_budget: Optional[float] = None
    # Estado de cierre para proyectos puntuales (fecha final + horas vs tiempo). None en recurrentes.
    closing_status: Optional[dict] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ProjectListResponse(BaseModel):
    id: int
    name: str
    project_type: Optional[str]
    is_recurring: bool = False
    requires_task_review: bool = False
    start_date: Optional[datetime]
    target_end_date: Optional[datetime]
    status: str
    progress_percent: Optional[int]
    gsc_url: Optional[str] = None
    ga4_property_id: Optional[str] = None
    # La tarifa es la fuente de verdad del pricing, pero el listado no la
    # devolvía: el tipo de TS sí la declaraba, así que en tiempo de ejecución
    # llegaba undefined y no había forma de ver el fee sin abrir cada proyecto.
    pricing_model: Optional[str] = None
    monthly_fee: Optional[float] = None
    client_id: int
    client_name: Optional[str] = None
    owner_id: Optional[int] = None
    owner_name: Optional[str] = None
    phase_count: int = 0
    task_count: Optional[int] = None
    completed_task_count: Optional[int] = None

    model_config = {"from_attributes": True}


class ProjectLifecycleTaskSample(BaseModel):
    id: int
    title: str
    status: str
    href: str


class ProjectLifecycleTimerSample(BaseModel):
    id: int
    task_id: int
    href: Optional[str] = None


class ProjectLifecycleCount(BaseModel):
    total: int
    sample: list[ProjectLifecycleTaskSample] | list[ProjectLifecycleTimerSample]


class ProjectCloseBlockers(BaseModel):
    active_tasks: ProjectLifecycleCount
    waiting_count: int
    in_review_count: int
    active_timers: ProjectLifecycleCount


class ProjectLifecycleRecurrence(BaseModel):
    templates: int
    paused: int
    suppressed_after_close: int


class ProjectClosePreview(BaseModel):
    project_id: int
    target: Literal["completed", "cancelled"]
    current_status: str
    expected_updated_at: datetime
    preview_revision: str
    can_close: bool
    blockers: ProjectCloseBlockers
    recurrence: ProjectLifecycleRecurrence


class ProjectCloseRequest(BaseModel):
    target: Literal["completed", "cancelled"]
    expected_updated_at: datetime
    preview_revision: str


class ProjectReopenPreview(BaseModel):
    project_id: int
    current_status: str
    expected_updated_at: datetime
    preview_revision: str
    can_reopen: bool
    recurrence: ProjectLifecycleRecurrence
    message: str


class ProjectReopenRequest(BaseModel):
    expected_updated_at: datetime
    preview_revision: str


class ProjectTaskItemResponse(BaseModel):
    id: int
    title: str
    status: str
    priority: str
    start_date: Optional[datetime] = None
    due_date: Optional[datetime] = None
    scheduled_date: Optional[date] = None
    estimated_minutes: Optional[int] = None
    assigned_to: Optional[int] = None
    assigned_user_name: Optional[str] = None
    waiting_for: Optional[str] = None
    follow_up_date: Optional[date] = None
    is_recurring: bool = False


class ProjectTaskPhaseSummary(BaseModel):
    id: int
    name: str
    order_index: int
    status: str
    phase_type: str
    start_date: Optional[datetime] = None
    due_date: Optional[datetime] = None


class ProjectTaskGroupResponse(BaseModel):
    phase: ProjectTaskPhaseSummary
    tasks: list[ProjectTaskItemResponse]


class ProjectTasksResponse(BaseModel):
    project_id: int
    project_name: str
    phases: list[ProjectTaskGroupResponse]
    unassigned_tasks: list[ProjectTaskItemResponse]


class ProjectCycleTaskResponse(BaseModel):
    id: int
    title: str
    status: str
    scheduled_date: Optional[date] = None
    completed_at: Optional[datetime] = None


class ProjectMonthlyCycleResponse(BaseModel):
    project_id: int
    month: str
    period_start: date
    period_end: date
    planned_count: int
    completed_in_month_count: int
    total_minutes: Optional[int]
    used_hours: Optional[float]
    budget_hours: Optional[float] = None
    remaining_hours: Optional[float] = None
    tasks: list[ProjectCycleTaskResponse]


class ProjectExtract(BaseModel):
    name: str
    description: Optional[str] = None
    project_type: Optional[str] = None
    is_recurring: bool = False
    budget_amount: Optional[float] = None
    start_date: Optional[str] = None
    target_end_date: Optional[str] = None
    client_name: Optional[str] = None
    pricing_model: Optional[str] = None
    monthly_fee: Optional[float] = None
    unit_price: Optional[float] = None
    unit_label: Optional[str] = None
    scope: Optional[str] = None


# --- Template Schemas ---

class TemplatePhaseInput(BaseModel):
    name: str
    default_days: int = 7

class TemplateTaskInput(BaseModel):
    phase: int = 0
    title: str
    minutes: int = 60

class TemplateCreate(BaseModel):
    name: str
    key: Optional[str] = None
    description: Optional[str] = None
    project_type: Optional[str] = None
    is_recurring: bool = False
    phases: list[TemplatePhaseInput] = []
    default_tasks: list[TemplateTaskInput] = []
    pricing_model: Optional[str] = None
    monthly_fee: Optional[float] = None

class TemplateUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    project_type: Optional[str] = None
    is_recurring: Optional[bool] = None
    phases: Optional[list[TemplatePhaseInput]] = None
    default_tasks: Optional[list[TemplateTaskInput]] = None
    pricing_model: Optional[str] = None
    monthly_fee: Optional[float] = None

class SaveAsTemplateInput(BaseModel):
    name: Optional[str] = None
    key: Optional[str] = None
    description: Optional[str] = None

class InvoiceTasksInput(BaseModel):
    task_ids: list[int]


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
