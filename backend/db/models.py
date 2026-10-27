import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Index,
    CheckConstraint,
    Column,
    Integer,
    String,
    Float,
    SmallInteger,
    Numeric,
    Text,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Boolean,
    JSON,
    LargeBinary,
    UniqueConstraint,
    func,
    literal_column, Sequence, REAL, BigInteger,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, relationship


"""SQLAlchemy ORM models for The Agency.

Model inventory (38 models, ~1,500 lines):

  --- Core ---
  Base, TimestampMixin
  User, UserPermission

  --- Client Management ---
  Client, ClientContact, ClientDocument

  --- Project Management ---
  Project, ProjectPhase, ProjectTemplateDB

  --- Tasks & Time ---
  TaskCategory, Task, TaskChecklist, TaskComment, TaskAttachment, TimeEntry

  --- Proposals & Leads ---
  ServiceTemplate, Proposal, Lead, LeadActivity

  --- Calendar & Events ---
  Event

  --- Communications ---
  CommunicationLog

  --- PM Intelligence ---
  PMInsight, AlertSettings

  --- Growth ---
  GrowthIdea

  --- Financial ---
  Income, Expense, ExpenseCategory, Tax, Forecast,
  FinancialSettings, FinancialInsight, MonthlyClose,
  AdvisorTask, AdvisorAiBrief, AdvisorAiBriefPayload,
  Invoice, InvoiceItem, BillingEvent, BalanceSnapshot

  --- Integrations ---
  HoldedSyncLog, HoldedInvoiceCache, HoldedExpenseCache,
  DiscordSettings, SyncLog, CsvMapping

  --- Reports & Digests ---
  WeeklyDigest, DailyUpdate

  --- Undo ---
  ChangeLog

  --- Notifications & Inbox ---
  Notification, InboxNote, InboxAttachment

  --- Holidays ---
  CompanyHoliday

NOTE: Do NOT split this file into separate modules.
SQLAlchemy relationships require all models to share the same
DeclarativeBase registry and be importable from a single place.
"""


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)


class UTCTimestampMixin:
    """Naive UTC storage independent of the PostgreSQL session timezone."""
    created_at = Column(DateTime, default=func.timezone("UTC", func.clock_timestamp()), nullable=False)
    updated_at = Column(DateTime, default=func.timezone("UTC", func.clock_timestamp()), onupdate=func.timezone("UTC", func.clock_timestamp()), nullable=False)


# ═══════════════════════════════════════════════════════════════
# ENUMS
# ═══════════════════════════════════════════════════════════════

class UserRole(str, enum.Enum):
    admin = "admin"
    member = "member"


class ContractType(str, enum.Enum):
    monthly = "monthly"
    one_time = "one_time"


class ClientStatus(str, enum.Enum):
    active = "active"
    paused = "paused"
    finished = "finished"


class VATTreatment(str, enum.Enum):
    domestic_21 = "domestic_21"          # SL a SL en España: factura incluye 21% IVA
    intracom_exempt = "intracom_exempt"  # UE intracomunitario (inversión sujeto pasivo)
    andorra_exempt = "andorra_exempt"    # Andorra (sin IVA)
    extracom_exempt = "extracom_exempt"  # Fuera UE (exportación de servicios)


class TaskStatus(str, enum.Enum):
    backlog = "backlog"
    pending = "pending"
    in_progress = "in_progress"
    waiting = "waiting"
    in_review = "in_review"
    advanced = "advanced"      # avanzada hoy: vuelve a in_progress de madrugada
    completed = "completed"


#: "En curso" a efectos de informes: ``advanced`` es una tarea en curso que
#: hoy se ha dado por cerrada en el daily, no un estado terminal.
IN_PROGRESS_TASK_STATUSES = [TaskStatus.in_progress, TaskStatus.advanced]

#: Estados en los que la tarea sigue viva (todo menos completada).
#: Fuente única: cualquier listado explícito de estados debería salir de aquí,
#: para que añadir un estado nuevo no deje contadores e informes desfasados.
ACTIVE_TASK_STATUSES = [s for s in TaskStatus if s is not TaskStatus.completed]


class TaskPriority(str, enum.Enum):
    urgent = "urgent"
    high = "high"
    medium = "medium"
    low = "low"


class ProjectStatus(str, enum.Enum):
    planning = "planning"
    active = "active"
    on_hold = "on_hold"
    completed = "completed"
    cancelled = "cancelled"


class PhaseStatus(str, enum.Enum):
    pending = "pending"
    in_progress = "in_progress"
    completed = "completed"


class PhaseType(str, enum.Enum):
    sprint = "sprint"
    milestone = "milestone"
    standard = "standard"


class EventType(str, enum.Enum):
    meeting = "meeting"
    deadline = "deadline"
    reminder = "reminder"
    other = "other"


class CommunicationChannel(str, enum.Enum):
    email = "email"
    call = "call"
    meeting = "meeting"
    whatsapp = "whatsapp"
    slack = "slack"
    other = "other"


class CommunicationDirection(str, enum.Enum):
    inbound = "inbound"
    outbound = "outbound"


class InsightType(str, enum.Enum):
    deadline = "deadline"
    stalled = "stalled"
    overdue = "overdue"
    followup = "followup"
    workload = "workload"
    suggestion = "suggestion"
    operational_suggestion = "operational_suggestion"
    quality = "quality"
    financial = "financial"


class InsightPriority(str, enum.Enum):
    high = "high"
    medium = "medium"
    low = "low"


class InsightStatus(str, enum.Enum):
    active = "active"
    dismissed = "dismissed"
    acted = "acted"


class ServiceType(str, enum.Enum):
    seo_sprint = "seo_sprint"
    migration = "migration"
    market_study = "market_study"
    consulting_retainer = "consulting_retainer"
    partnership_retainer = "partnership_retainer"
    brand_audit = "brand_audit"
    custom = "custom"


class ProposalStatus(str, enum.Enum):
    draft = "draft"
    sent = "sent"
    accepted = "accepted"
    rejected = "rejected"
    expired = "expired"


class DailyUpdateStatus(str, enum.Enum):
    draft = "draft"
    sent = "sent"


class DigestStatus(str, enum.Enum):
    draft = "draft"
    reviewed = "reviewed"
    sent = "sent"


class DigestTone(str, enum.Enum):
    formal = "formal"
    cercano = "cercano"
    equipo = "equipo"


class ReportCadence(str, enum.Enum):
    weekly = "weekly"
    monthly = "monthly"


class ExternalDeliveryAction(str, enum.Enum):
    confirmed = "confirmed"
    revoked = "revoked"


class LeadStatus(str, enum.Enum):
    new = "new"
    contacted = "contacted"
    discovery = "discovery"
    proposal = "proposal"
    negotiation = "negotiation"
    won = "won"
    lost = "lost"


class LeadSource(str, enum.Enum):
    website = "website"
    referral = "referral"
    linkedin = "linkedin"
    conference = "conference"
    cold_outreach = "cold_outreach"
    other = "other"


class LeadActivityType(str, enum.Enum):
    note = "note"
    email_sent = "email_sent"
    email_received = "email_received"
    call = "call"
    meeting = "meeting"
    proposal_sent = "proposal_sent"
    status_change = "status_change"
    followup_set = "followup_set"


class BillingCycle(str, enum.Enum):
    monthly = "monthly"
    bimonthly = "bimonthly"
    quarterly = "quarterly"
    annual = "annual"
    one_time = "one_time"


class BillingEventType(str, enum.Enum):
    invoice_sent = "invoice_sent"
    payment_received = "payment_received"
    reminder_sent = "reminder_sent"
    note = "note"


class GrowthFunnelStage(str, enum.Enum):
    referral = "referral"
    desire = "desire"
    activate = "activate"
    revenue = "revenue"
    retention = "retention"
    other = "other"


class GrowthStatus(str, enum.Enum):
    idea = "idea"
    in_progress = "in_progress"
    completed = "completed"
    discarded = "discarded"


# ═══════════════════════════════════════════════════════════════
# CORE: Users & Permissions
# ═══════════════════════════════════════════════════════════════

class User(TimestampMixin, Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    full_name = Column(String(255), nullable=False)
    role = Column(Enum(UserRole), nullable=False, default=UserRole.member)
    hourly_rate = Column(Numeric(10, 2), nullable=True)
    cost_per_hour = Column(Numeric(10, 2), nullable=False, default=0, server_default="0")
    available_hours_month = Column(Numeric(5, 1), nullable=False, default=147, server_default="147")
    weekly_hours = Column(Float, nullable=False, default=40.0)
    is_active = Column(Boolean, nullable=False, default=True)
    password_reset_required = Column(Boolean, nullable=False, default=False)
    preferences = Column(JSONB, nullable=True, server_default="{}")
    region = Column(String(10), nullable=True)      # CCAA code: "MAD", "CAT"...
    locality = Column(String(100), nullable=True)    # City: "Madrid", "Barcelona"...
    short_name = Column(String(50), nullable=True)   # Display name: "David", "Nacho"
    birthday = Column(Date, nullable=True)
    job_title = Column(String(100), nullable=True)   # "SEO Strategist", "PM"
    morning_reminder_time = Column(String(5), nullable=False, default="08:00", server_default="08:00")
    evening_reminder_time = Column(String(5), nullable=False, default="18:00", server_default="18:00")
    onboarding_completed = Column(Boolean, nullable=False, default=False, server_default="false")
    # Google Calendar integration
    google_refresh_token = Column(String(500), nullable=True)   # encrypted v1:
    google_calendar_id = Column(String(200), nullable=True)     # "primary" or specific
    google_calendar_synced_at = Column(DateTime, nullable=True)  # last complete committed calendar reconciliation (UTC)
    google_calendar_connected = Column(Boolean, nullable=False, default=False, server_default="false")

    tasks = relationship("Task", back_populates="assigned_user", lazy="selectin", foreign_keys="[Task.assigned_to]")
    permissions = relationship("UserPermission", back_populates="user", lazy="selectin", cascade="all, delete-orphan")


# ═══════════════════════════════════════════════════════════════
# CLIENT MANAGEMENT: Clients, Contacts, Resources, Documents
# ═══════════════════════════════════════════════════════════════

class Client(UTCTimestampMixin, Base):
    __tablename__ = "clients"
    __table_args__ = (
        CheckConstraint("monthly_budget >= 0", name="ck_client_monthly_budget_positive"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    email = Column(String(255), nullable=True)
    phone = Column(String(50), nullable=True)
    company = Column(String(255), nullable=True)
    website = Column(String(255), nullable=True)
    contract_type = Column(Enum(ContractType), nullable=False, default=ContractType.monthly)
    monthly_budget = Column(Numeric(12, 2), nullable=True)
    status = Column(Enum(ClientStatus), nullable=False, default=ClientStatus.active)
    notes = Column(Text, nullable=True)
    # Financial fields (from GF)
    currency = Column(String(10), nullable=False, default="EUR")
    monthly_fee = Column(Numeric(12, 2), nullable=True)
    # Holded integration
    holded_contact_id = Column(String(100), nullable=True)
    vat_number = Column(String(50), nullable=True)
    vat_treatment = Column(Enum(VATTreatment), nullable=False, default=VATTreatment.domestic_21, server_default="domestic_21")
    # Analytics settings
    ga4_property_id = Column(String(50), nullable=True)
    gsc_url = Column(String(255), nullable=True)
    # Control SEO: términos que marcan una búsqueda como "de marca" (≤ 20).
    brand_terms = Column(JSONB, nullable=False, default=list, server_default="[]")
    # Control SEO: grupos de URL propios [{name, rules: [{type, value}]}] (≤ 30).
    seo_page_groups = Column(JSONB, nullable=False, default=list, server_default="[]")
    # Leads por landing (GA4): eventos que cuentan como lead. Nombre exacto o
    # prefijo terminado en "*" ("generate_lead_*"). Ver `services/ga4_leads.py`.
    ga4_lead_events = Column(JSONB, nullable=False, default=lambda: ["generate_lead"],
                             server_default='["generate_lead"]')
    # Billing settings
    billing_cycle = Column(Enum(BillingCycle), nullable=True)
    billing_day = Column(Integer, nullable=True)  # 1-28
    next_invoice_date = Column(Date, nullable=True)
    last_invoiced_date = Column(Date, nullable=True)
    engine_project_id = Column(Integer, nullable=True)
    # ``vigil_slug`` (y la tabla ``vigil_summary``) siguen en la BD pero fuera del
    # ORM desde la fase 3b de Vigil; se borran en la 3c (docs/vigil-migration.md).
    # ``scripts/import_vigil.py`` la lee con SQL.
    # Internal flag
    is_internal = Column(Boolean, nullable=False, default=False)
    # Narrative context / dossier
    context = Column(Text, nullable=True)
    # Intermediary agency
    intermediary_name = Column(String(200), nullable=True)
    is_intermediary_deal = Column(Boolean, nullable=False, default=False)
    # Revenue intelligence
    # Engine cached metrics (synced periodically)
    engine_content_count = Column(Integer, nullable=True)
    engine_keyword_count = Column(Integer, nullable=True)
    engine_avg_position = Column(Float, nullable=True)
    engine_clicks_30d = Column(Integer, nullable=True)
    engine_impressions_30d = Column(Integer, nullable=True)
    engine_metrics_synced_at = Column(DateTime(timezone=True), nullable=True)
    engine_summary_data = Column(JSONB, nullable=True)
    engine_alerts_data = Column(JSONB, nullable=True)
    # AI-generated onboarding intelligence
    onboarding_intelligence = Column(JSONB, nullable=True)
    # Per-client Slack digest template (null = default format)
    slack_template = Column(JSONB, nullable=True)

    tasks = relationship("Task", back_populates="client", lazy="noload")
    projects = relationship("Project", back_populates="client", lazy="noload")
    communications = relationship("CommunicationLog", back_populates="client", lazy="noload", order_by="CommunicationLog.occurred_at.desc()")
    contacts = relationship("ClientContact", back_populates="client", lazy="noload", order_by="ClientContact.is_primary.desc()")
    incomes = relationship("Income", back_populates="client", lazy="noload")
    billing_events = relationship("BillingEvent", back_populates="client", lazy="noload", order_by="BillingEvent.event_date.desc()")


# ═══════════════════════════════════════════════════════════════
# TASKS & TIME TRACKING
# ═══════════════════════════════════════════════════════════════

class TaskCategory(TimestampMixin, Base):
    __tablename__ = "task_categories"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False, unique=True)
    default_minutes = Column(Integer, nullable=False, default=60)

    tasks = relationship("Task", back_populates="category", lazy="selectin")


# ═══════════════════════════════════════════════════════════════
# PROJECT MANAGEMENT: Projects, Phases, Evidence
# ═══════════════════════════════════════════════════════════════

class Project(UTCTimestampMixin, Base):
    __tablename__ = "projects"
    __table_args__ = (
        CheckConstraint("budget_amount >= 0", name="ck_project_budget_amount_positive"),
        CheckConstraint("budget_hours >= 0", name="ck_project_budget_hours_positive"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    project_type = Column(String(50), nullable=True)  # seo_audit, content_strategy, linkbuilding, technical_seo, custom
    start_date = Column(DateTime, nullable=True)
    target_end_date = Column(DateTime, nullable=True)
    actual_end_date = Column(DateTime, nullable=True)
    status = Column(Enum(ProjectStatus), nullable=False, default=ProjectStatus.active)
    progress_percent = Column(Integer, nullable=False, default=0)
    budget_hours = Column(Float, nullable=True)
    weekly_hours_budget = Column(Float, nullable=True)  # guía visual de carga semanal; no dispara alertas por sí solo
    monthly_hours_budget = Column(Float, nullable=True)  # techo acumulado del mes; aviso 75 %, alerta 100 %
    # Lo que sobra (o el exceso) del mes anterior suma (o resta) al techo de este
    # mes; sólo un mes, sin cadena. Ver services/hours_carryover.py.
    hours_carryover = Column(Boolean, nullable=False, default=False, server_default="false")
    budget_amount = Column(Numeric(12, 2), nullable=True)
    gsc_url = Column(String(255), nullable=True)
    ga4_property_id = Column(String(50), nullable=True)
    is_recurring = Column(Boolean, nullable=False, default=False)
    requires_task_review = Column(Boolean, nullable=False, default=False, server_default="false")
    engine_project_id = Column(Integer, nullable=True)
    # Pricing & scope
    pricing_model = Column(String(20), nullable=True)  # monthly, per_piece, hourly, project
    monthly_fee = Column(Numeric(12, 2), nullable=True)  # retainer mensual que factura este proyecto (BASE sin IVA)
    fee_is_base = Column(Boolean, nullable=False, default=True, server_default="true")  # monthly_fee en base imponible
    unit_price = Column(Numeric(12, 2), nullable=True)
    unit_label = Column(String(50), nullable=True)  # e.g. "pieza", "artículo", "hora"
    scope = Column(Text, nullable=True)
    # Project billing schedule
    billing_day = Column(Integer, nullable=True)  # 1-28, day of month
    billing_amount = Column(Numeric(12, 2), nullable=True)  # amount per billing cycle
    next_billing_date = Column(Date, nullable=True)
    last_billed_date = Column(Date, nullable=True)

    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)

    client = relationship("Client", back_populates="projects", lazy="selectin")
    owner = relationship("User", lazy="selectin", foreign_keys=[owner_id])
    phases = relationship("ProjectPhase", back_populates="project", lazy="selectin", order_by="ProjectPhase.order_index")
    tasks = relationship("Task", back_populates="project", lazy="selectin")


class ProjectPhase(TimestampMixin, Base):
    __tablename__ = "project_phases"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    order_index = Column(Integer, nullable=False, default=0)
    phase_type = Column(Enum(PhaseType), nullable=False, default=PhaseType.standard)
    start_date = Column(DateTime, nullable=True)
    due_date = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    status = Column(Enum(PhaseStatus), nullable=False, default=PhaseStatus.pending)

    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)

    project = relationship("Project", back_populates="phases", lazy="selectin")
    tasks = relationship("Task", back_populates="phase", lazy="selectin")


# ═══════════════════════════════════════════════════════════════
# PROPOSALS & SALES: Templates, Proposals, Leads
# ═══════════════════════════════════════════════════════════════

class ServiceTemplate(TimestampMixin, Base):
    __tablename__ = "service_templates"

    id = Column(Integer, primary_key=True, autoincrement=True)
    service_type = Column(Enum(ServiceType), unique=True, nullable=False)
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)

    is_recurring = Column(Boolean, default=False)
    price_range_min = Column(Numeric(10, 2), nullable=True)
    price_range_max = Column(Numeric(10, 2), nullable=True)

    default_phases = Column(JSON, nullable=True)
    default_includes = Column(Text, nullable=True)
    default_excludes = Column(Text, nullable=True)

    prompt_context = Column(Text, nullable=True)


class Proposal(TimestampMixin, Base):
    __tablename__ = "proposals"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # Vinculación
    lead_id = Column(Integer, ForeignKey("leads.id"), nullable=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True, index=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)

    # Datos de la propuesta
    title = Column(String(300), nullable=False)
    contact_name = Column(String(200), nullable=True)
    company_name = Column(String(200), nullable=False, default="")

    # Tipo de servicio
    service_type = Column(Enum(ServiceType), nullable=True)

    # Contexto (input del usuario)
    situation = Column(Text, nullable=True)
    problem = Column(Text, nullable=True)
    cost_of_inaction = Column(Text, nullable=True)
    opportunity = Column(Text, nullable=True)
    approach = Column(Text, nullable=True)
    relevant_cases = Column(Text, nullable=True)

    # Opciones de precio (siempre 2-3)
    pricing_options = Column(JSON, nullable=True)

    # Cálculo interno (NUNCA visible en la propuesta generada)
    internal_hours_david = Column(Numeric(10, 1), nullable=True)
    internal_hours_nacho = Column(Numeric(10, 1), nullable=True)
    internal_cost_estimate = Column(Numeric(10, 2), nullable=True)
    estimated_margin_percent = Column(Numeric(5, 2), nullable=True)

    # Contenido generado por IA
    generated_content = Column(JSON, nullable=True)

    # Estado y tracking
    status = Column(Enum(ProposalStatus), nullable=False, default=ProposalStatus.draft)
    sent_at = Column(DateTime, nullable=True)
    responded_at = Column(DateTime, nullable=True)
    response_notes = Column(Text, nullable=True)
    valid_until = Column(Date, nullable=True)

    # Si aceptada → proyecto creado
    converted_project_id = Column(Integer, ForeignKey("projects.id"), nullable=True, index=True)

    # Legacy fields (kept for backward compat)
    budget = Column(Numeric(12, 2), nullable=True)
    scope = Column(Text, nullable=True)

    # Relaciones
    lead = relationship("Lead", lazy="selectin")
    client = relationship("Client", lazy="selectin")
    created_by_user = relationship("User", lazy="selectin")
    converted_project = relationship("Project", foreign_keys=[converted_project_id], lazy="selectin")


# ═══════════════════════════════════════════════════════════════
# CALENDAR & EVENTS
# ═══════════════════════════════════════════════════════════════

class Event(TimestampMixin, Base):
    __tablename__ = "events"
    __table_args__ = (Index("uq_events_google_scope", "user_id", "source_calendar_id", "google_event_id", unique=True),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    event_type = Column(Enum(EventType), nullable=False, default=EventType.other)
    start_time = Column(DateTime, nullable=False)
    end_time = Column(DateTime, nullable=True)
    is_all_day = Column(Boolean, nullable=False, default=False)

    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    # Google Calendar sync
    google_event_id = Column(String(300), nullable=True)
    source_calendar_id = Column(String(200), nullable=True)
    source = Column(String(20), nullable=False, default="manual", server_default="manual")
    alert_sent_at = Column(DateTime, nullable=True)

    client = relationship("Client", lazy="selectin")
    project = relationship("Project", lazy="selectin")
    user = relationship("User", lazy="selectin")


class Task(TimestampMixin, Base):
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    status = Column(Enum(TaskStatus), nullable=False, default=TaskStatus.pending)
    priority = Column(Enum(TaskPriority), nullable=False, default=TaskPriority.medium, server_default="medium")
    estimated_minutes = Column(Integer, nullable=True)
    actual_minutes = Column(Integer, nullable=True)
    start_date = Column(DateTime, nullable=True)
    due_date = Column(DateTime, nullable=True)
    is_inbox = Column(Boolean, nullable=False, default=False)

    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True, index=True)
    category_id = Column(Integer, ForeignKey("task_categories.id"), nullable=True, index=True)
    assigned_to = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True, index=True)
    phase_id = Column(Integer, ForeignKey("project_phases.id"), nullable=True, index=True)
    depends_on = Column(Integer, ForeignKey("tasks.id"), nullable=True, index=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    scheduled_date = Column(Date, nullable=True)
    # Orden manual (índice fraccional, services/task_rank.py); NULL = sin orden manual.
    sort_rank = Column(String(64), nullable=True)
    # Fecha en que se marcó como "Avanzada". La barrida nocturna devuelve a
    # in_progress toda tarea advanced con advanced_at anterior a hoy, de modo
    # que un servidor caído a medianoche se recupera solo al arrancar.
    advanced_at = Column(Date, nullable=True)
    # Real completion transition; legacy rows remain unknown rather than using updated_at.
    completed_at = Column(DateTime, nullable=True, index=True)
    # Withdrawal preserves status, dates and all historical time/source links.
    retired_at = Column(DateTime, nullable=True)
    retired_reason = Column(String(500), nullable=True)
    waiting_for = Column(String(255), nullable=True)
    follow_up_date = Column(Date, nullable=True)
    link_url = Column(Text, nullable=True)

    # Per-task billing
    unit_cost = Column(Numeric(12, 2), nullable=True)
    invoiced_at = Column(DateTime(timezone=True), nullable=True)

    # Recurring task fields
    is_recurring = Column(Boolean, nullable=False, default=False, server_default="false")
    recurrence_pattern = Column(String(20), nullable=True)  # daily|weekly|biweekly|monthly
    recurrence_day = Column(Integer, nullable=True)  # 0-4 for weekly, 1-28 for monthly
    recurrence_end_date = Column(Date, nullable=True)
    # NULL preserves the historical ISO-even-week calendar. Never backfill it.
    recurrence_anchor_date = Column(Date, nullable=True)
    recurrence_paused_at = Column(DateTime, nullable=True)
    # Stable generation identity; rescheduling never changes this date.
    # Historical instances stay NULL because their original date is unknown.
    recurrence_occurrence_date = Column(Date, nullable=True)
    recurring_parent_id = Column(Integer, ForeignKey("tasks.id"), nullable=True, index=True)
    # Written procedure of a recurring template. Each generated occurrence
    # keeps its own copy, so editing the template only changes future ones.
    procedure_text = Column(Text, nullable=True)
    procedure_url = Column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "(retired_at IS NULL AND retired_reason IS NULL) OR "
            "(retired_at IS NOT NULL AND retired_reason IS NOT NULL AND length(btrim(retired_reason)) > 0)",
            name="ck_tasks_retirement_pair",
        ),
        Index(
            "uq_task_recurring_occurrence", "recurring_parent_id", "recurrence_occurrence_date",
            unique=True, postgresql_where=recurring_parent_id.is_not(None),
        ),
    )

    client = relationship("Client", back_populates="tasks", lazy="selectin")
    category = relationship("TaskCategory", back_populates="tasks", lazy="selectin")
    assigned_user = relationship("User", back_populates="tasks", lazy="selectin", foreign_keys=[assigned_to])
    creator = relationship("User", lazy="selectin", foreign_keys=[created_by])
    time_entries = relationship("TimeEntry", back_populates="task", lazy="noload")
    project = relationship("Project", back_populates="tasks", lazy="selectin")
    phase = relationship("ProjectPhase", back_populates="tasks", lazy="selectin")
    dependency = relationship("Task", remote_side="Task.id", lazy="selectin", foreign_keys=[depends_on])
    recurring_parent = relationship("Task", remote_side="Task.id", lazy="selectin", foreign_keys=[recurring_parent_id])
    checklist_items = relationship("TaskChecklist", back_populates="task", lazy="selectin", cascade="all, delete-orphan", order_by="TaskChecklist.order_index")


class TaskRecurrenceOccurrence(Base):
    """A consumed calendar date survives deletion of its generated task."""
    __tablename__ = "task_recurrence_occurrences"

    id = Column(Integer, primary_key=True, autoincrement=True)
    template_id = Column(Integer, ForeignKey("tasks.id"), nullable=False)
    date = Column(Date, nullable=False)
    task_id = Column(Integer, ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.timezone("UTC", func.now()))

    __table_args__ = (
        Index("uq_task_recurrence_consumed", "template_id", "date", unique=True),
        Index("ix_task_recurrence_generated", "task_id"),
    )


class TaskTimeBlock(TimestampMixin, Base):
    """Bloque de trabajo con hora: "trabajo en la tarea X de 10:00 a 11:30".

    Horas civiles de la agencia sin zona (como ``Event``). Varios por tarea y
    persona; lo lee Mi agenda (vista con horas) y el cronómetro se arranca desde
    él. Migración ``task_time_blocks_v1``; entra en el Deshacer como hijo de la
    tarea.
    """
    __tablename__ = "task_time_blocks"
    __table_args__ = (
        CheckConstraint("ends_at > starts_at", name="ck_task_time_blocks_order"),
        CheckConstraint("ends_at - starts_at <= interval '12 hours'", name="ck_task_time_blocks_length"),
        CheckConstraint(
            "starts_at::date = (ends_at - interval '1 microsecond')::date",
            name="ck_task_time_blocks_same_day",
        ),
        Index("ix_task_time_blocks_user_starts", "user_id", "starts_at"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(Integer, ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    starts_at = Column(DateTime, nullable=False)
    ends_at = Column(DateTime, nullable=False)

    task = relationship("Task", lazy="noload")

    @property
    def display_label(self) -> str:
        """Para el Deshacer: "28/10 10:00–11:30"."""
        if not self.starts_at or not self.ends_at:
            return "Bloque"
        return f"{self.starts_at:%d/%m %H:%M}–{self.ends_at:%H:%M}"


class TaskChecklist(TimestampMixin, Base):
    __tablename__ = "task_checklists"

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(Integer, ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    text = Column(String(500), nullable=False)
    description = Column(Text, nullable=True)
    is_done = Column(Boolean, nullable=False, default=False)
    order_index = Column(Integer, nullable=False, default=0)
    assigned_to = Column(Integer, ForeignKey("users.id"), nullable=True)
    due_date = Column(Date, nullable=True)

    task = relationship("Task", back_populates="checklist_items", lazy="noload")
    assigned_user = relationship("User", lazy="selectin")


class TaskComment(TimestampMixin, Base):
    __tablename__ = "task_comments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(Integer, ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    text = Column(Text, nullable=False)
    # Borrador de IA pedido por user_id desde el procedimiento de la tarea.
    is_ai_draft = Column(Boolean, nullable=False, default=False, server_default="false")

    user = relationship("User", lazy="selectin")


class TaskAttachment(TimestampMixin, Base):
    __tablename__ = "task_attachments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(Integer, ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    mime_type = Column(String(100), nullable=False, default="application/octet-stream")
    size_bytes = Column(Integer, nullable=False)
    content = Column(LargeBinary, nullable=False)
    uploaded_by = Column(Integer, ForeignKey("users.id"), nullable=True)

    uploader = relationship("User", lazy="selectin")


class TimeEntry(TimestampMixin, Base):
    __tablename__ = "time_entries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    minutes = Column(Integer, nullable=True)  # null = timer running
    started_at = Column(DateTime, nullable=True)  # set when timer starts
    paused_at = Column(DateTime, nullable=True)  # set when timer is paused
    accumulated_seconds = Column(Integer, nullable=False, default=0, server_default="0")  # seconds accumulated before pause
    date = Column(DateTime, nullable=False, default=func.now())
    notes = Column(Text, nullable=True)

    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    task = relationship("Task", back_populates="time_entries", lazy="selectin")
    user = relationship("User", lazy="selectin")


# ── Client sub-models (contacts, resources, documents) ────────

class ClientContact(UTCTimestampMixin, Base):
    __tablename__ = "client_contacts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    name = Column(String(200), nullable=False)
    email = Column(String(255), nullable=True)
    phone = Column(String(50), nullable=True)
    position = Column(String(100), nullable=True)  # "CEO", "Marketing Manager"
    is_primary = Column(Boolean, nullable=False, default=False)
    notes = Column(Text, nullable=True)
    department = Column(String(100), nullable=True)
    preferred_channel = Column(String(50), nullable=True)  # email, call, whatsapp, etc.
    language = Column(String(50), nullable=True)  # es, en, ca, etc.
    linkedin_url = Column(String(300), nullable=True)

    client = relationship("Client", back_populates="contacts", lazy="selectin")


class ClientDocument(TimestampMixin, Base):
    __tablename__ = "client_documents"

    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(Integer, ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    mime_type = Column(String(100), nullable=False, default="application/octet-stream")
    size_bytes = Column(Integer, nullable=False)
    content = Column(LargeBinary, nullable=False)

    client = relationship("Client", lazy="noload")


# ═══════════════════════════════════════════════════════════════
# BILLING & INVOICING
# ═══════════════════════════════════════════════════════════════

class BillingEvent(TimestampMixin, Base):
    __tablename__ = "billing_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    event_type = Column(Enum(BillingEventType), nullable=False)
    amount = Column(Numeric(12, 2), nullable=True)
    invoice_number = Column(String(100), nullable=True)
    notes = Column(Text, nullable=True)
    event_date = Column(Date, nullable=False)

    client = relationship("Client", back_populates="billing_events", lazy="selectin")


# ═══════════════════════════════════════════════════════════════
# COMMUNICATIONS & PM INTELLIGENCE
# ═══════════════════════════════════════════════════════════════

class CommunicationLog(TimestampMixin, Base):
    __tablename__ = "communication_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    channel = Column(Enum(CommunicationChannel), nullable=False)
    direction = Column(Enum(CommunicationDirection), nullable=False)
    subject = Column(String(200), nullable=True)
    summary = Column(Text, nullable=False)
    contact_name = Column(String(100), nullable=True)
    occurred_at = Column(DateTime, nullable=False)
    requires_followup = Column(Boolean, nullable=False, default=False)
    followup_date = Column(DateTime, nullable=True)
    followup_notes = Column(Text, nullable=True)

    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    contact_id = Column(Integer, ForeignKey("client_contacts.id"), nullable=True, index=True)

    client = relationship("Client", back_populates="communications", lazy="selectin")
    user = relationship("User", lazy="selectin")
    contact = relationship("ClientContact", lazy="selectin")


class PMInsight(TimestampMixin, Base):
    __tablename__ = "pm_insights"

    id = Column(Integer, primary_key=True, autoincrement=True)
    insight_type = Column(Enum(InsightType), nullable=False)
    priority = Column(Enum(InsightPriority), nullable=False)
    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=False)
    suggested_action = Column(Text, nullable=True)
    status = Column(Enum(InsightStatus), nullable=False, default=InsightStatus.active)
    dismissed_at = Column(DateTime, nullable=True)
    acted_at = Column(DateTime, nullable=True)
    generated_at = Column(DateTime, nullable=False)
    expires_at = Column(DateTime, nullable=True)

    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True, index=True)
    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=True, index=True)

    user = relationship("User", lazy="selectin")
    client = relationship("Client", lazy="selectin")
    project = relationship("Project", lazy="selectin")
    task = relationship("Task", lazy="selectin")


class Invoice(TimestampMixin, Base):
    __tablename__ = "invoices"

    id = Column(Integer, primary_key=True, autoincrement=True)
    invoice_number = Column(String(50), unique=True, nullable=False)
    amount = Column(Numeric(12, 2), nullable=False)
    issued_date = Column(DateTime, nullable=False, default=func.now())
    paid = Column(Boolean, nullable=False, default=False)
    notes = Column(Text, nullable=True)

    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)

    client = relationship("Client", lazy="selectin")


class InvoiceItem(TimestampMixin, Base):
    __tablename__ = "invoice_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    description = Column(String(255), nullable=False)
    quantity = Column(Float, nullable=False, default=1)
    unit_price = Column(Numeric(12, 2), nullable=False)

    invoice_id = Column(Integer, ForeignKey("invoices.id"), nullable=False, index=True)
    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=True, index=True)

    invoice = relationship("Invoice", lazy="selectin")
    task = relationship("Task", lazy="selectin")


# ═══════════════════════════════════════════════════════════════
# AUDIT, SETTINGS & REPORTS
# ═══════════════════════════════════════════════════════════════

class AuditLog(TimestampMixin, Base):
    """Append-only log of authenticated API requests + entity-level audit events.

    The original schema modelled entity-level audit (action/entity_type/entity_id).
    That subsystem was never persisted (log_audit() writes to stderr only) so the
    table was empty. Reused here as a request analytics sink: a middleware writes
    one row per authenticated API call with route_template + method + status +
    duration. The legacy entity columns are kept nullable for backward compat in
    case future code wants to log entity events alongside requests.
    """
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    # Legacy entity-audit fields (nullable for request-only rows)
    action = Column(String(50), nullable=True)
    entity_type = Column(String(50), nullable=True)
    entity_id = Column(Integer, nullable=True)
    details = Column(Text, nullable=True)
    # Request analytics fields
    method = Column(String(10), nullable=True)
    route_template = Column(String(255), nullable=True, index=True)
    status_code = Column(Integer, nullable=True)
    duration_ms = Column(Integer, nullable=True)
    # Declared client application. This is analytics context, never identity
    # or authorization; historical rows intentionally remain NULL.
    client_origin = Column(String(12), nullable=True)

    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)

    user = relationship("User", lazy="selectin")


class ChangeLog(TimestampMixin, Base):
    """Journal de cambios deshacibles — una fila por ACCIÓN de usuario.

    No confundir con :class:`AuditLog`, que hoy es un sink de analítica de
    requests (ruta + método + duración) y no guarda el contenido del cambio.

    Una fila = una transacción confirmada por un usuario autenticado. El campo
    ``operations`` lleva la lista de filas tocadas en esa transacción, cada una
    con su snapshot antes/después:

        [{"entity_type": "project", "entity_id": 12, "action": "delete",
          "before": {...}, "after": null}, ...]

    Se agrupa así a propósito: borrar un proyecto desvincula sus tareas en la
    misma transacción, y el usuario espera deshacer *eso* de una vez, no ir
    tarea por tarea. Lo escribe backend/services/change_journal.py vía eventos
    ORM; lo consume backend/api/routes/changes.py.
    """
    __tablename__ = "change_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    # Entidad "protagonista" de la acción, la que da título a la entrada.
    entity_type = Column(String(50), nullable=False)
    entity_id = Column(Integer, nullable=True)
    action = Column(String(10), nullable=False)  # create | update | delete
    label = Column(String(255), nullable=False)
    operations = Column(JSONB, nullable=False)
    undone_at = Column(DateTime, nullable=True)
    undone_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


class ClientOnboardingReceipt(Base):
    """Terminal result or cancellation barrier for a user's client creation."""
    __tablename__ = "client_onboarding_receipts"
    __table_args__ = (
        CheckConstraint(
            "(status = 'cancelled' AND request_hash IS NULL AND result IS NULL AND change_log_id IS NULL) OR "
            "(status = 'confirmed' AND request_hash IS NOT NULL AND request_hash ~ '^[0-9a-f]{64}$' "
            "AND result IS NOT NULL AND jsonb_typeof(result) = 'object')",
            name="ck_client_onboarding_receipts_terminal",
        ),
        CheckConstraint("request_key ~ '^[A-Za-z0-9_-]{16,64}$'", name="ck_client_onboarding_receipts_key"),
    )

    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    request_key = Column(String(64), primary_key=True)
    status = Column(String(16), nullable=False)
    request_hash = Column(String(64), nullable=True)
    result = Column(JSONB(none_as_null=True), nullable=True)
    change_log_id = Column(Integer, ForeignKey("change_logs.id", ondelete="SET NULL"), nullable=True)


class CommandReceipt(TimestampMixin, Base):
    """Durable, user-owned receipt for one natural-language command."""
    __tablename__ = "command_receipts"
    __table_args__ = (
        UniqueConstraint("user_id", "request_key", name="uq_command_receipts_user_key"),
        Index("ix_command_receipts_user_created", "user_id", "created_at"),
    )

    id = Column(String(36), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    request_key = Column(String(64), nullable=False)
    request_hash = Column(String(64), nullable=False)
    channel = Column(String(12), nullable=False)
    context = Column(JSONB, nullable=True)
    raw_text = Column(Text, nullable=False)
    status = Column(String(20), nullable=False)
    intent = Column(JSONB, nullable=True)
    prompt = Column(JSONB, nullable=True)
    result = Column(JSONB, nullable=True)
    change_log_id = Column(Integer, ForeignKey("change_logs.id", ondelete="SET NULL"), nullable=True)
    error_code = Column(String(50), nullable=True)
    error_detail = Column(Text, nullable=True)
    revision = Column(Integer, nullable=False, default=1)
    step_replays = Column(JSONB, nullable=False, default=dict)


class MonthlyClose(TimestampMixin, Base):
    __tablename__ = "monthly_closes"
    __table_args__ = (
        UniqueConstraint("year", "month", name="uq_monthly_close_period"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    year = Column(Integer, nullable=False)
    month = Column(Integer, nullable=False)
    reviewed_numbers = Column(Boolean, nullable=False, default=False)
    reviewed_margin = Column(Boolean, nullable=False, default=False)
    reviewed_cash_buffer = Column(Boolean, nullable=False, default=False)
    reviewed_reinvestment = Column(Boolean, nullable=False, default=False)
    reviewed_debt = Column(Boolean, nullable=False, default=False)
    reviewed_taxes = Column(Boolean, nullable=False, default=False)
    reviewed_personal = Column(Boolean, nullable=False, default=False)
    reviewed_holded = Column(Boolean, nullable=False, default=False)
    responsible_name = Column(String, nullable=False, default="")
    notes = Column(Text, nullable=False, default="")


class FinancialSettings(TimestampMixin, Base):
    __tablename__ = "financial_settings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tax_reserve = Column(Numeric(12, 2), nullable=False, default=0)
    credit_limit = Column(Numeric(12, 2), nullable=False, default=0)
    credit_used = Column(Numeric(12, 2), nullable=False, default=0)
    monthly_close_day = Column(Integer, nullable=False, default=5)
    credit_alert_pct = Column(Numeric(5, 2), nullable=False, default=70)
    tax_reserve_target_pct = Column(Numeric(5, 2), nullable=False, default=20)
    # GF fields
    default_vat_rate = Column(Numeric(5, 2), nullable=False, default=21.0)
    corporate_tax_rate = Column(Numeric(5, 2), nullable=False, default=25.0)
    irpf_retention_rate = Column(Numeric(5, 2), nullable=False, default=15.0)
    cash_start = Column(Numeric(12, 2), nullable=False, default=0.0)
    # Advisor thresholds
    advisor_expense_alert_pct = Column(Numeric(5, 2), nullable=False, default=20.0)
    advisor_margin_warning_pct = Column(Numeric(5, 2), nullable=False, default=10.0)
    # AI config
    ai_provider = Column(String(50), nullable=False, default="openai-compatible")
    ai_model = Column(String(100), nullable=False, default="")
    ai_api_url = Column(String(500), nullable=False, default="")
    ai_api_key = Column(String(500), nullable=False, default="")


class AlertSettings(TimestampMixin, Base):
    __tablename__ = "alert_settings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, unique=True)

    # Thresholds
    days_without_activity = Column(Integer, nullable=False, default=14)
    days_before_deadline = Column(Integer, nullable=False, default=3)
    days_without_contact = Column(Integer, nullable=False, default=10)
    max_tasks_per_week = Column(Integer, nullable=False, default=15)

    notify_in_app = Column(Boolean, nullable=False, default=True)
    notify_email = Column(Boolean, nullable=False, default=False)

    user = relationship("User", lazy="selectin")


class ReportType(str, enum.Enum):
    client_status = "client_status"
    weekly_summary = "weekly_summary"
    project_status = "project_status"
    client_monthly = "client_monthly"


class ReportAudience(str, enum.Enum):
    executive = "executive"
    marketing = "marketing"
    operational = "operational"


# ── User Permissions & Invitations ────────────────────────────

class UserPermission(TimestampMixin, Base):
    __tablename__ = "user_permissions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    module = Column(String(50), nullable=False)
    can_read = Column(Boolean, nullable=False, default=True)
    can_write = Column(Boolean, nullable=False, default=False)

    user = relationship("User", back_populates="permissions", lazy="selectin")


# ═══════════════════════════════════════════════════════════════
# GROWTH ENGINE (ICE experiments)
# ═══════════════════════════════════════════════════════════════

class GrowthIdea(TimestampMixin, Base):
    __tablename__ = "growth_ideas"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    funnel_stage = Column(Enum(GrowthFunnelStage), nullable=False, default=GrowthFunnelStage.other)
    target_kpi = Column(String(100), nullable=True)
    status = Column(Enum(GrowthStatus), nullable=False, default=GrowthStatus.idea)
    
    # ICE Framework
    impact = Column(Integer, nullable=False, default=5)       # 1-10
    confidence = Column(Integer, nullable=False, default=5)   # 1-10
    ease = Column(Integer, nullable=False, default=5)         # 1-10
    ice_score = Column(Integer, nullable=False, default=125)  # I * C * E

    # Tracking
    experiment_start_date = Column(DateTime, nullable=True)
    experiment_end_date = Column(DateTime, nullable=True)
    results_notes = Column(Text, nullable=True)
    is_successful = Column(Boolean, nullable=True)

    # Optional Link to Project or Task for execution tracking
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True, index=True)
    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=True, index=True)

    project = relationship("Project", lazy="selectin")
    task = relationship("Task", lazy="selectin")


# ═══════════════════════════════════════════════════════════════
# FINANCIAL (ported from Gestor Financiero)
# Income, Expenses, Taxes, Forecasts, Advisor
# ═══════════════════════════════════════════════════════════════

class WeeklyDigest(UTCTimestampMixin, Base):
    __tablename__ = "weekly_digests"

    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    period_start = Column(Date, nullable=False)
    period_end = Column(Date, nullable=False)
    status = Column(Enum(DigestStatus), nullable=False, default=DigestStatus.draft)
    tone = Column(Enum(DigestTone), nullable=False, default=DigestTone.cercano)
    content = Column(JSON, nullable=True)  # {greeting, date, sections: {done, need, next}, closing}
    raw_context = Column(JSON, nullable=True)  # datos crudos pasados a Claude
    generated_at = Column(DateTime, nullable=True)
    edited_at = Column(DateTime, nullable=True)

    created_by = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    client = relationship("Client", lazy="selectin")
    creator = relationship("User", lazy="selectin")


class ClientReportPolicy(UTCTimestampMixin, Base):
    __tablename__ = "client_report_policies"

    client_id = Column(Integer, ForeignKey("clients.id", ondelete="CASCADE"), primary_key=True)
    # Un cliente puede tener informe mensual y seguimiento semanal a la vez, cada
    # uno con su interruptor; responsable y revisión son comunes. La cadencia de
    # un resumen sale de su periodo (``digest_periods.period_cadence``).
    weekly_enabled = Column(Boolean, nullable=False, default=False, server_default="false")
    monthly_enabled = Column(Boolean, nullable=False, default=False, server_default="false")
    responsible_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    revision = Column(Integer, nullable=False, default=1, server_default="1")


class DigestExternalDeliveryEvent(Base):
    __tablename__ = "digest_external_delivery_events"
    __table_args__ = (
        Index("uq_digest_external_event_request", "actor_id", "request_key", unique=True),
        Index("ix_digest_external_event_digest_created", "digest_id", "created_at"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    digest_id = Column(Integer, ForeignKey("weekly_digests.id", ondelete="RESTRICT"), nullable=False)
    action = Column(Enum(ExternalDeliveryAction, native_enum=False), nullable=False)
    actor_id = Column(Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    request_key = Column(String(80), nullable=False)
    request_hash = Column(String(64), nullable=False)
    created_at = Column(DateTime, default=func.timezone("UTC", func.clock_timestamp()), nullable=False)


class Lead(TimestampMixin, Base):
    __tablename__ = "leads"

    id = Column(Integer, primary_key=True, autoincrement=True)
    # Datos basicos
    company_name = Column(String(200), nullable=False)
    contact_name = Column(String(200), nullable=True)
    email = Column(String(200), nullable=True)
    phone = Column(String(50), nullable=True)
    website = Column(String(300), nullable=True)
    linkedin_url = Column(String(300), nullable=True)

    # Pipeline
    status = Column(Enum(LeadStatus), nullable=False, default=LeadStatus.new)
    source = Column(Enum(LeadSource), nullable=False, default=LeadSource.other)
    assigned_to = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)

    # Valor y servicio
    estimated_value = Column(Numeric(10, 2), nullable=True)
    service_interest = Column(String(100), nullable=True)
    currency = Column(String(3), nullable=False, default="EUR")

    # Contexto
    notes = Column(Text, nullable=True)
    industry = Column(String(100), nullable=True)
    company_size = Column(String(50), nullable=True)
    current_website_traffic = Column(String(100), nullable=True)

    # Seguimiento
    next_followup_date = Column(Date, nullable=True)
    next_followup_notes = Column(Text, nullable=True)
    last_contacted_at = Column(DateTime, nullable=True)
    estimated_close_date = Column(Date, nullable=True)
    probability = Column(Integer, nullable=True)  # 0-100

    # Conversion
    converted_client_id = Column(Integer, ForeignKey("clients.id"), nullable=True, index=True)
    converted_at = Column(DateTime, nullable=True)
    lost_reason = Column(Text, nullable=True)

    # Relaciones
    assigned_user = relationship("User", lazy="selectin")
    converted_client = relationship("Client", lazy="selectin")
    activities = relationship("LeadActivity", back_populates="lead", lazy="selectin", order_by="LeadActivity.created_at.desc()")


class LeadActivity(TimestampMixin, Base):
    __tablename__ = "lead_activities"

    id = Column(Integer, primary_key=True, autoincrement=True)
    lead_id = Column(Integer, ForeignKey("leads.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    activity_type = Column(Enum(LeadActivityType), nullable=False)
    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)

    lead = relationship("Lead", back_populates="activities", lazy="selectin")
    user = relationship("User", lazy="selectin")


class ExpenseCategory(TimestampMixin, Base):
    __tablename__ = "expense_categories"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), unique=True, nullable=False)
    description = Column(Text, nullable=False, default="")
    color = Column(String(20), nullable=False, default="#6B7280")
    is_active = Column(Boolean, nullable=False, default=True)

    expenses = relationship("Expense", back_populates="category", lazy="selectin")


class Income(TimestampMixin, Base):
    __tablename__ = "income"
    __table_args__ = (
        CheckConstraint("amount >= 0", name="ck_income_amount_non_negative"),
        CheckConstraint("vat_rate >= 0 AND vat_rate <= 100", name="ck_income_vat_rate_range"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(Date, nullable=False)
    description = Column(String(255), nullable=False)
    amount = Column(Numeric(12, 2), nullable=False)
    type = Column(String(50), nullable=False, default="factura")  # factura, recurrente, extra
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True, index=True)
    invoice_number = Column(String(100), nullable=False, default="")
    vat_rate = Column(Numeric(5, 2), nullable=False, default=21.0)
    vat_amount = Column(Numeric(12, 2), nullable=False, default=0.0)
    # Tax regime: standard (21% IVA), eu_reverse_charge, intracomunitario, export
    tax_regime = Column(String(50), nullable=False, default="standard")
    # IRPF withholding applied TO this invoice (e.g. client retains 15%)
    irpf_withholding_rate = Column(Numeric(5, 2), nullable=False, default=0.0)
    irpf_withholding_amount = Column(Numeric(12, 2), nullable=False, default=0.0)
    status = Column(String(50), nullable=False, default="cobrado")  # pendiente, cobrado
    notes = Column(Text, nullable=False, default="")
    due_date = Column(Date, nullable=True)

    client = relationship("Client", back_populates="incomes", lazy="selectin")


class Expense(TimestampMixin, Base):
    __tablename__ = "expenses"
    __table_args__ = (
        CheckConstraint("amount >= 0", name="ck_expense_amount_non_negative"),
        CheckConstraint("vat_rate >= 0 AND vat_rate <= 100", name="ck_expense_vat_rate_range"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(Date, nullable=False)
    description = Column(String(255), nullable=False)
    amount = Column(Numeric(12, 2), nullable=False)
    category_id = Column(Integer, ForeignKey("expense_categories.id"), nullable=True, index=True)
    is_recurring = Column(Boolean, nullable=False, default=False)
    recurrence_period = Column(String(50), nullable=False, default="")  # mensual, trimestral, anual
    vat_rate = Column(Numeric(5, 2), nullable=False, default=21.0)
    vat_amount = Column(Numeric(12, 2), nullable=False, default=0.0)
    is_deductible = Column(Boolean, nullable=False, default=True)
    # Tax regime: standard, eu_reverse_charge (auto-repercusión IVA), intracomunitario, import
    tax_regime = Column(String(50), nullable=False, default="standard")
    # IRPF withholding on this expense (e.g. freelancer retention)
    irpf_withholding_rate = Column(Numeric(5, 2), nullable=False, default=0.0)
    irpf_withholding_amount = Column(Numeric(12, 2), nullable=False, default=0.0)
    supplier = Column(String(255), nullable=False, default="")
    notes = Column(Text, nullable=False, default="")

    category = relationship("ExpenseCategory", back_populates="expenses", lazy="selectin")


class Tax(TimestampMixin, Base):
    __tablename__ = "taxes"
    __table_args__ = (
        CheckConstraint("status IN ('pendiente', 'pagado', 'aplazado')", name="ck_tax_status"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    model = Column(String(50), nullable=False, default="")  # 303, 200, 111, 115
    period = Column(String(50), nullable=False, default="")  # Q1, Q2, Q3, Q4, anual
    year = Column(Integer, nullable=False)
    base_amount = Column(Numeric(12, 2), nullable=False, default=0.0)
    tax_rate = Column(Numeric(5, 2), nullable=False, default=0.0)
    tax_amount = Column(Numeric(12, 2), nullable=False, default=0.0)
    status = Column(String(50), nullable=False, default="pendiente")  # pendiente, pagado, aplazado
    due_date = Column(Date, nullable=True)
    paid_date = Column(Date, nullable=True)
    notes = Column(Text, nullable=False, default="")


class Forecast(TimestampMixin, Base):
    __tablename__ = "forecasts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    month = Column(Date, nullable=False)
    projected_income = Column(Numeric(12, 2), nullable=False, default=0.0)
    projected_expenses = Column(Numeric(12, 2), nullable=False, default=0.0)
    projected_taxes = Column(Numeric(12, 2), nullable=False, default=0.0)
    projected_profit = Column(Numeric(12, 2), nullable=False, default=0.0)
    confidence = Column(Float, nullable=False, default=0.5)
    notes = Column(Text, nullable=False, default="")


class FinancialInsight(TimestampMixin, Base):
    __tablename__ = "financial_insights"

    id = Column(Integer, primary_key=True, autoincrement=True)
    type = Column(String(50), nullable=False)  # alerta, consejo, anomalia
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=False)
    severity = Column(String(50), nullable=False, default="info")  # info, warning, critical
    is_read = Column(Boolean, nullable=False, default=False)
    is_dismissed = Column(Boolean, nullable=False, default=False)


class AdvisorTask(TimestampMixin, Base):
    __tablename__ = "advisor_tasks"
    __table_args__ = (
        CheckConstraint("status IN ('open', 'done')", name="ck_advisor_task_status"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    source_key = Column(String(255), unique=True, nullable=False)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=False, default="")
    status = Column(String(50), nullable=False, default="open")  # open, done
    priority = Column(String(50), nullable=False, default="medium")  # low, medium, high
    due_date = Column(Date, nullable=True)


class AdvisorAiBrief(TimestampMixin, Base):
    __tablename__ = "advisor_ai_briefs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    period_start = Column(Date, nullable=True)
    period_end = Column(Date, nullable=True)
    content = Column(Text, nullable=False, default="")
    model = Column(String(100), nullable=False, default="")
    provider = Column(String(50), nullable=False, default="openai-compatible")

    payloads = relationship("AdvisorAiBriefPayload", back_populates="brief", lazy="selectin")


class AdvisorAiBriefPayload(TimestampMixin, Base):
    __tablename__ = "advisor_ai_brief_payloads"

    id = Column(Integer, primary_key=True, autoincrement=True)
    brief_id = Column(Integer, ForeignKey("advisor_ai_briefs.id"), nullable=False, index=True)
    payload = Column(Text, nullable=False, default="")

    brief = relationship("AdvisorAiBrief", back_populates="payloads", lazy="selectin")


class SyncLog(TimestampMixin, Base):
    __tablename__ = "sync_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source = Column(String(50), nullable=False)  # csv, bank, manual
    file_name = Column(String(255), nullable=False, default="")
    records_processed = Column(Integer, nullable=False, default=0)
    records_imported = Column(Integer, nullable=False, default=0)
    records_skipped = Column(Integer, nullable=False, default=0)
    errors = Column(Text, nullable=False, default="")
    status = Column(String(50), nullable=False, default="completado")  # en_proceso, completado, error


class CsvMapping(TimestampMixin, Base):
    __tablename__ = "csv_mappings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    target = Column(String(50), nullable=False, default="expenses")  # expenses, income
    mapping = Column(JSON, nullable=False)
    delimiter = Column(String(5), nullable=False, default=",")


# ── Holded Integration ─────────────────────────────────────


class HoldedSyncLog(Base):
    __tablename__ = "holded_sync_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    sync_type = Column(String(50), nullable=False)  # contacts, invoices, expenses
    status = Column(String(20), nullable=False, default="in_progress")  # success, error, partial
    records_synced = Column(Integer, default=0)
    error_message = Column(Text, nullable=True)
    started_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)


class HoldedInvoiceCache(Base):
    __tablename__ = "holded_invoices_cache"

    id = Column(Integer, primary_key=True, autoincrement=True)
    holded_id = Column(String(100), unique=True, nullable=False)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True, index=True)
    contact_name = Column(String(300), nullable=True)
    invoice_number = Column(String(100), nullable=True)
    date = Column(Date, nullable=True)
    due_date = Column(Date, nullable=True)
    total = Column(Numeric(10, 2), default=0)
    subtotal = Column(Numeric(10, 2), default=0)
    tax = Column(Numeric(10, 2), default=0)
    status = Column(String(50), nullable=True)  # paid, pending, overdue
    currency = Column(String(3), default="EUR")
    raw_data = Column(JSON, nullable=True)
    synced_at = Column(DateTime, default=datetime.utcnow)

    client = relationship("Client", lazy="selectin")


class HoldedExpenseCache(Base):
    __tablename__ = "holded_expenses_cache"

    id = Column(Integer, primary_key=True, autoincrement=True)
    holded_id = Column(String(100), unique=True, nullable=False)
    description = Column(String(300), nullable=True)
    date = Column(Date, nullable=True)
    total = Column(Numeric(10, 2), default=0)
    subtotal = Column(Numeric(10, 2), default=0)
    tax = Column(Numeric(10, 2), default=0)
    category = Column(String(100), nullable=True)
    supplier = Column(String(300), nullable=True)
    status = Column(String(50), nullable=True)
    raw_data = Column(JSON, nullable=True)
    synced_at = Column(DateTime, default=datetime.utcnow)


# ── Discord Settings ─────────────────────────────────────


class DiscordSettings(Base):
    __tablename__ = "discord_settings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    webhook_url = Column(String(500), nullable=True)
    bot_token = Column(String(500), nullable=True)
    channel_id = Column(String(50), nullable=True)  # Cached from webhook info
    auto_daily_summary = Column(Boolean, default=False)
    summary_time = Column(String(5), default="18:00")  # HH:MM
    include_ai_note = Column(Boolean, default=True)
    last_sent_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())


# ── Daily Updates ─────────────────────────────────────


class DailyUpdate(TimestampMixin, Base):
    __tablename__ = "daily_updates"
    __table_args__ = (Index("uq_daily_user_date", "user_id", "date", unique=True),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    date = Column(Date, nullable=False)
    raw_text = Column(Text, nullable=False)
    parsed_data = Column(JSON, nullable=True)  # {projects: [{name, client, tasks: [{description, details}]}]}
    revision = Column(Integer, nullable=False, default=1, server_default="1")
    source_facts = Column(JSON, nullable=False, default=list, server_default="[]")
    status = Column(Enum(DailyUpdateStatus), nullable=False, default=DailyUpdateStatus.draft)
    discord_sent_at = Column(DateTime, nullable=True)

    user = relationship("User", lazy="selectin")


class CommunicationRequest(TimestampMixin, Base):
    """Reviewed manual snapshot: a real source for deliveries without a draft model."""
    __tablename__ = "communication_requests"
    __table_args__ = (Index("uq_communication_request_key", "request_key", unique=True),)
    id = Column(Integer, primary_key=True, autoincrement=True)
    request_key = Column(String(64), nullable=False)
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    kind = Column(String(30), nullable=False)
    scope = Column(String(10), nullable=False)
    period_start = Column(Date, nullable=False)
    period_end = Column(Date, nullable=False)
    title = Column(String(200), nullable=False)
    content = Column(Text, nullable=False)
    destination_kind = Column(String(20), nullable=False)


class CommunicationSchedule(TimestampMixin, Base):
    __tablename__ = "communication_schedules"
    __table_args__ = (Index("uq_communication_policy_key", "policy_key", unique=True),)
    id = Column(Integer, primary_key=True)
    policy_key = Column(String(100), nullable=False)
    destination_id = Column(String(30), nullable=True)  # explicit technical weekly recipient, never User identity
    kind = Column(String(20), nullable=False)
    approved_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    recipient_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    enabled = Column(Boolean, nullable=False, default=False)
    channels = Column(JSONB, nullable=False)
    time = Column(String(5), nullable=True)
    minutes_before = Column(Integer, nullable=True)
    quiet_start = Column(String(5), nullable=True)
    quiet_end = Column(String(5), nullable=True)
    revision = Column(Integer, nullable=False, default=1)
    effective_from = Column(DateTime, nullable=False)


class CommunicationOccurrence(TimestampMixin, Base):
    __tablename__ = "communication_occurrences"
    __table_args__ = (
        Index("uq_communication_occurrence_key", "occurrence_key", unique=True),
        Index("uq_communication_occurrence_request", "request_id", unique=True),
        Index("uq_communication_occurrence_notification", "notification_id", unique=True),
        Index("ix_communication_occurrence_due", "state", "due_at"),
    )
    id = Column(Integer, primary_key=True)
    occurrence_key = Column(String(64), nullable=False)
    schedule_id = Column(Integer, ForeignKey("communication_schedules.id"), nullable=False)
    recipient_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    kind = Column(String(20), nullable=False)
    channel = Column(String(20), nullable=False)
    period_start = Column(Date, nullable=False)
    period_end = Column(Date, nullable=False)
    event_id = Column(Integer, ForeignKey("events.id", ondelete="SET NULL"), nullable=True)
    event_start = Column(DateTime, nullable=True)  # revision: business civil time
    due_at = Column(DateTime, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    state = Column(String(20), nullable=False, default="planned")
    reason = Column(Text, nullable=True)
    request_id = Column(Integer, ForeignKey("communication_requests.id"), nullable=True)
    notification_id = Column(Integer, ForeignKey("notifications.id", ondelete="SET NULL"), nullable=True)


class Delivery(TimestampMixin, Base):
    """Immutable message intent; source edits never replace its snapshot."""
    __tablename__ = "deliveries"
    __table_args__ = (
        Index("uq_deliveries_key", "dedupe_key", unique=True),
        Index("ix_deliveries_pending", "status", "available_at"),
        Index("ix_deliveries_source", "source_kind", "source_id"),
    )
    id = Column(String(36), primary_key=True)
    dedupe_key = Column(String(64), nullable=False)
    actor_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    source_kind = Column(String(20), nullable=False)
    source_id = Column(Integer, nullable=False)
    source_version = Column(String(64), nullable=False)
    destination_key = Column(String(64), nullable=False)
    payload = Column(JSONB, nullable=False)
    status = Column(String(20), nullable=False, default="pending")
    available_at = Column(DateTime, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    sent_at = Column(DateTime, nullable=True)
    error_code = Column(String(50), nullable=True)
    message = Column(Text, nullable=True)
    resend_of = Column(String(36), ForeignKey("deliveries.id"), nullable=True)


class DeliveryAttempt(TimestampMixin, Base):
    __tablename__ = "delivery_attempts"
    __table_args__ = (Index("uq_delivery_attempt_number", "delivery_id", "number", unique=True),)
    id = Column(String(36), primary_key=True)  # also the fencing token
    delivery_id = Column(String(36), ForeignKey("deliveries.id"), nullable=False)
    number = Column(Integer, nullable=False)
    status = Column(String(20), nullable=False)
    lease_until = Column(DateTime, nullable=False)
    steps = Column(JSONB, nullable=False)


class BalanceSnapshot(TimestampMixin, Base):
    __tablename__ = "balance_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(Date, nullable=False, unique=True)
    amount = Column(Numeric(12, 2), nullable=False)
    notes = Column(Text, nullable=False, default="")


class Notification(TimestampMixin, Base):
    __tablename__ = "notifications"

    __table_args__ = (
        Index("uq_notifications_user_dedupe", "user_id", "dedupe_key", unique=True),
        Index("ix_notifications_incident_state", "user_id", "incident_state", "id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    type = Column(String(50), nullable=False)  # task_assigned, task_overdue, lead_followup, digest_pending
    title = Column(String(255), nullable=False)
    message = Column(Text, nullable=True)
    is_read = Column(Boolean, nullable=False, default=False)
    link_url = Column(String(500), nullable=True)  # e.g. "/tasks?id=123"
    entity_type = Column(String(50), nullable=True)  # task, lead, digest
    entity_id = Column(Integer, nullable=True)
    dedupe_key = Column(String(255), nullable=True)

    # NULL state distinguishes historical activity from reconciled conditions.
    incident_state = Column(String(20), nullable=True)
    incident_severity = Column(String(10), nullable=True)
    incident_revision = Column(Integer, nullable=True)
    incident_detected_at = Column(DateTime, nullable=True)
    incident_fingerprint = Column(String(64), nullable=True)
    incident_snoozed_until = Column(DateTime, nullable=True)
    incident_resolved_at = Column(DateTime, nullable=True)
    incident_resolution_reason = Column(String(50), nullable=True)
    incident_dismissal_reason = Column(String(500), nullable=True)
    entity_key = Column(String(80), nullable=True)

    user = relationship("User", lazy="selectin")


# ── Inbox Quick Capture ────────────────────────────────────


class InboxNoteStatus(str, enum.Enum):
    pending = "pending"
    classified = "classified"
    processed = "processed"
    dismissed = "dismissed"


class InboxNote(TimestampMixin, Base):
    __tablename__ = "inbox_notes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    raw_text = Column(Text, nullable=False)
    source = Column(String(20), nullable=False, default="dashboard")
    status = Column(Enum(InboxNoteStatus), nullable=False, default=InboxNoteStatus.pending)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True, index=True)
    resolved_as = Column(String(20), nullable=True)
    resolved_entity_id = Column(Integer, nullable=True)
    ai_suggestion = Column(JSONB, nullable=True)
    classification_error_code = Column(String(32), nullable=True)
    classification_next_attempt_at = Column(DateTime, nullable=True)
    link_url = Column(String(500), nullable=True)

    user = relationship("User", lazy="selectin")
    project = relationship("Project", lazy="selectin")
    client = relationship("Client", lazy="selectin")
    attachments = relationship("InboxAttachment", back_populates="note", cascade="all, delete-orphan", lazy="selectin")


Index(
    "ix_inbox_pending_attempt",
    func.coalesce(InboxNote.classification_next_attempt_at, literal_column("TIMESTAMP 'epoch'")),
    InboxNote.id,
    postgresql_where=InboxNote.status == InboxNoteStatus.pending,
)


class InboxAttachment(TimestampMixin, Base):
    __tablename__ = "inbox_attachments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    note_id = Column(Integer, ForeignKey("inbox_notes.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    mime_type = Column(String(100), nullable=False, default="application/octet-stream")
    size_bytes = Column(Integer, nullable=False)
    content = Column(LargeBinary, nullable=False)
    uploaded_by = Column(Integer, ForeignKey("users.id"), nullable=True)

    note = relationship("InboxNote", back_populates="attachments")
    uploader = relationship("User", lazy="selectin")


# ── Company Holidays ─────────────────


class CompanyHoliday(TimestampMixin, Base):
    __tablename__ = "company_holidays"
    __table_args__ = (
        UniqueConstraint("date", "region", "locality", name="uq_holiday_date_region_locality"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(Date, nullable=False, index=True)
    name = Column(String(100), nullable=False)
    country = Column(String(5), nullable=False, default="ES")
    region = Column(String(10), nullable=True)      # CCAA code: "MAD", "CAT", "AND"...
    locality = Column(String(100), nullable=True)    # City: "Madrid", "Barcelona"...


# ── Project Templates (DB-backed) ──────────────────────────

class ProjectTemplateDB(TimestampMixin, Base):
    __tablename__ = "project_templates"

    id = Column(Integer, primary_key=True, autoincrement=True)
    key = Column(String(50), nullable=False, unique=True, index=True)
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    project_type = Column(String(50), nullable=True)
    is_recurring = Column(Boolean, nullable=False, default=False)
    phases = Column(JSON, nullable=False, default=list)       # [{name, default_days}]
    default_tasks = Column(JSON, nullable=False, default=list) # [{phase, title, minutes}]
    pricing_model = Column(String(20), nullable=True)
    monthly_fee = Column(Numeric(12, 2), nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    creator = relationship("User", lazy="selectin")


class JobRuntime(Base):
    """Latest scheduled cycle; configuration and labels live in the job catalog."""
    __tablename__ = "job_runtime"

    key = Column(String(64), primary_key=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    success_at = Column(DateTime(timezone=True), nullable=True)
    error_code = Column(String(64), nullable=True)
    next_run_at = Column(DateTime(timezone=True), nullable=True)


class GscConnection(Base):
    """Una cuenta de Google conectada a Search Console (puede haber varias)."""
    __tablename__ = "gsc_connection"

    # Secuencia explícita: con autoincrement, create_all la haría SERIAL (int4)
    # y el contrato publicado (gsc_v1) exige SMALLINT. Es la misma secuencia
    # que crea la migración gsc_accounts_v1.
    id = Column(SmallInteger, Sequence("gsc_connection_id_seq"), primary_key=True)
    google_email = Column(String(255), nullable=True)  # en minúsculas; único
    refresh_token = Column(Text, nullable=False)  # cifrado con encrypt_vault_secret
    status = Column(String(32), nullable=False)  # connected | reconnect_required
    connected_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    connected_at = Column(DateTime(timezone=True), nullable=False)


Index(
    "uq_gsc_connection_google_email", GscConnection.google_email, unique=True,
    postgresql_where=GscConnection.google_email.isnot(None),
)


class Ga4Daily(Base):
    """Totales diarios de una propiedad de GA4: sesiones, eventos clave y lo que llega desde asistentes de IA."""
    __tablename__ = "ga4_daily"

    property_id = Column(String(32), primary_key=True)
    date = Column(Date, primary_key=True)
    sessions = Column(Integer, nullable=False)
    key_events = Column(Float, nullable=False)
    ai_sessions = Column(Integer, nullable=False)
    ai_key_events = Column(Float, nullable=False)


class Ga4PropertySync(Base):
    """Estado de importación por propiedad de GA4 y con qué cuenta de Google se lee."""
    __tablename__ = "ga4_property_sync"

    property_id = Column(String(32), primary_key=True)
    connection_id = Column(SmallInteger, ForeignKey("gsc_connection.id", ondelete="SET NULL"), nullable=True)
    backfilled_at = Column(DateTime(timezone=True), nullable=True)
    last_synced_at = Column(DateTime(timezone=True), nullable=True)
    last_data_date = Column(Date, nullable=True)
    error_code = Column(String(64), nullable=True)
    # Leads por landing (`ga4_lead_daily`): cuándo se importaron los 16 meses,
    # con qué eventos (si cambian, se vuelve a importar todo) y hasta qué día.
    leads_backfilled_at = Column(DateTime(timezone=True), nullable=True)
    leads_events = Column(String(1000), nullable=True)
    leads_synced_through = Column(Date, nullable=True)
    # Primer día que importó The Agency: lo anterior sólo puede venir de Engine.
    leads_covered_from = Column(Date, nullable=True)
    leads_error_code = Column(String(64), nullable=True)


class Ga4LeadDaily(Base):
    """Leads por día, landing y canal de una propiedad de GA4 (hasta 16 meses).

    `leads` = número de eventos que el cliente cuenta como lead
    (`clients.ga4_lead_events`). `landing_page` = host + ruta sin parámetros de
    seguimiento (recortada a 2.000 caracteres). Nada por usuario.
    """
    __tablename__ = "ga4_lead_daily"
    __table_args__ = (
        CheckConstraint("char_length(landing_page) <= 2000", name="ck_ga4_lead_daily_landing_length"),
    )

    property_id = Column(String(32), primary_key=True)
    date = Column(Date, primary_key=True)
    landing_page = Column(Text, primary_key=True)
    channel = Column(String(64), primary_key=True)
    leads = Column(Integer, nullable=False)


class GscDaily(Base):
    """Totales diarios finales de una propiedad de Search Console."""
    __tablename__ = "gsc_daily"

    site_url = Column(String(255), primary_key=True)
    date = Column(Date, primary_key=True)
    clicks = Column(Integer, nullable=False)
    impressions = Column(Integer, nullable=False)
    position = Column(Float, nullable=False)


class AppSuggestion(Base):
    """Idea o fallo de la app que deja alguien del equipo (botón "Sugerencias").

    Los admins las ven todas y las marcan como hechas; quien la escribió ve
    las suyas. `page_path` es la pantalla desde la que se envió.
    """
    __tablename__ = "app_suggestions"
    __table_args__ = (CheckConstraint("length(btrim(text)) > 0", name="ck_app_suggestions_text"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    author_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    text = Column(Text, nullable=False)
    page_path = Column(String(500), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    done_at = Column(DateTime(timezone=True), nullable=True)
    done_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


class AppSuggestionImage(Base):
    """Pantallazo de una sugerencia (sólo imágenes; se borra con ella)."""
    __tablename__ = "app_suggestion_images"
    __table_args__ = (
        CheckConstraint(
            "mime_type IN ('image/png','image/jpeg','image/gif','image/webp')",
            name="ck_app_suggestion_images_type",
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    suggestion_id = Column(Integer, ForeignKey("app_suggestions.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    mime_type = Column(String(50), nullable=False)
    size_bytes = Column(Integer, nullable=False)
    content = Column(LargeBinary, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


SCOPE_DECISIONS = ("pending", "absorb", "bill", "swap")


class ClientScopeRequest(Base):
    """Petición de un cliente fuera de lo contratado (llamada, Slack, email).

    Se apunta con su coste estimado en minutos y se decide qué hacer con ella:
    ``pending`` (sin decidir), ``absorb`` (la asumimos), ``bill`` (se factura
    aparte) o ``swap`` (se hace a cambio de otra cosa del plan). El mes al que
    cuenta es el de ``requested_on``. Migración ``client_scope_requests_v1``.
    """
    __tablename__ = "client_scope_requests"
    __table_args__ = (
        CheckConstraint("length(btrim(title)) > 0", name="ck_client_scope_requests_title"),
        CheckConstraint(
            "estimated_minutes > 0 AND estimated_minutes <= 60000",
            name="ck_client_scope_requests_minutes",
        ),
        CheckConstraint(
            "decision IN ('pending','absorb','bill','swap')",
            name="ck_client_scope_requests_decision",
        ),
        CheckConstraint(
            "(decision = 'pending') = (decided_at IS NULL)",
            name="ck_client_scope_requests_decided",
        ),
        Index("ix_client_scope_requests_client_requested", "client_id", "requested_on"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(Integer, ForeignKey("clients.id", ondelete="CASCADE"), nullable=False)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="SET NULL"), nullable=True, index=True)
    title = Column(String(200), nullable=False)
    detail = Column(Text, nullable=True)
    estimated_minutes = Column(Integer, nullable=False)
    requested_on = Column(Date, nullable=False)
    decision = Column(String(10), nullable=False, default="pending", server_default="pending")
    decision_note = Column(Text, nullable=True)
    decided_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    decided_at = Column(DateTime(timezone=True), nullable=True)
    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ClientShareLink(Base):
    """Enlace de sólo lectura para el cliente: sus resúmenes entregados y su tráfico.

    Sólo se guarda el SHA-256 del token; el enlace completo se enseña una vez al
    crearlo. Un enlace activo por cliente (índice único parcial).
    """
    __tablename__ = "client_share_links"

    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(Integer, ForeignKey("clients.id", ondelete="CASCADE"), nullable=False)
    token_hash = Column(String(64), nullable=False, unique=True)
    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    last_viewed_at = Column(DateTime(timezone=True), nullable=True)


Index(
    "uq_client_share_links_active", ClientShareLink.client_id, unique=True,
    postgresql_where=ClientShareLink.revoked_at.is_(None),
)


class GscSiteSync(Base):
    """Estado de importación por propiedad: decide si un mes está completo."""
    __tablename__ = "gsc_site_sync"

    site_url = Column(String(255), primary_key=True)
    backfilled_at = Column(DateTime(timezone=True), nullable=True)
    last_synced_at = Column(DateTime(timezone=True), nullable=True)
    last_data_date = Column(Date, nullable=True)
    error_code = Column(String(64), nullable=True)
    # Cuenta con la que se importa (la que tiene acceso a la propiedad).
    connection_id = Column(SmallInteger, ForeignKey("gsc_connection.id", ondelete="SET NULL"), nullable=True)


class GscQueryDaily(Base):
    """Cifras diarias finales por consulta de una propiedad (sólo los últimos 120 días).

    Google anonimiza las consultas poco frecuentes: la suma de consultas de un
    día es MENOR que el total de `gsc_daily` (la diferencia es "sin clasificar").
    """
    __tablename__ = "gsc_query_daily"

    site_url = Column(String(255), primary_key=True)
    date = Column(Date, primary_key=True)
    query = Column(Text, primary_key=True)
    clicks = Column(Integer, nullable=False)
    impressions = Column(Integer, nullable=False)
    position = Column(REAL, nullable=False)


class SeoAnnotation(Base):
    """Nota con fecha en las gráficas SEO de un cliente ("migramos la web", "cambio de títulos")."""
    __tablename__ = "seo_annotations"
    __table_args__ = (
        CheckConstraint("length(btrim(text)) > 0", name="ck_seo_annotations_text"),
        Index("ix_seo_annotations_client_date", "client_id", "date"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(Integer, ForeignKey("clients.id", ondelete="CASCADE"), nullable=False)
    date = Column(Date, nullable=False)
    text = Column(String(160), nullable=False)
    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class DigestSeoDetail(Base):
    """Foto del detalle de Search Console del mes de un resumen mensual: top de
    consultas y páginas, oportunidades y marca. Se pinta con código en el email,
    el PDF y el enlace del cliente; nunca va a la IA. Mientras el resumen no ha
    salido de la app se recalcula al pintarlo; después es lo que se envió.
    Fuera del Deshacer (dato de máquina) y con la retención del detalle."""
    __tablename__ = "digest_seo_details"
    __table_args__ = (Index("ix_digest_seo_details_site_url", "site_url"),)

    digest_id = Column(Integer, ForeignKey("weekly_digests.id", ondelete="CASCADE"), primary_key=True)
    site_url = Column(String(255), nullable=False)
    payload = Column(JSONB, nullable=False)
    computed_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class GscPageDaily(Base):
    """Cifras diarias finales por página de una propiedad (sólo los últimos 120 días).

    Las impresiones por página NO suman el total de la propiedad: una búsqueda
    que enseña dos páginas cuenta una impresión en cada una.
    """
    __tablename__ = "gsc_page_daily"

    site_url = Column(String(255), primary_key=True)
    date = Column(Date, primary_key=True)
    page = Column(Text, primary_key=True)  # recortada a 2.000 caracteres
    clicks = Column(Integer, nullable=False)
    impressions = Column(Integer, nullable=False)
    position = Column(REAL, nullable=False)


class GscDetailSync(Base):
    """Estado de importación del detalle (consultas y páginas) por propiedad."""
    __tablename__ = "gsc_detail_sync"

    site_url = Column(String(255), primary_key=True)
    backfilled_at = Column(DateTime(timezone=True), nullable=True)
    last_synced_at = Column(DateTime(timezone=True), nullable=True)
    last_data_date = Column(Date, nullable=True)
    error_code = Column(String(64), nullable=True)
    # Filas guardadas en la ventana de 120 días tras la última pasada.
    query_rows = Column(Integer, nullable=True)
    page_rows = Column(Integer, nullable=True)
    # Cuándo se importaron de Google los meses anteriores a los 120 días
    # (`gsc_query_monthly`). NULL = pendiente: la próxima pasada lo intenta.
    monthly_backfilled_at = Column(DateTime(timezone=True), nullable=True)


class GscQueryMonthly(Base):
    """Total MENSUAL por consulta de una propiedad: historial de posiciones más
    allá de los 120 días del detalle diario (hasta 16 meses).

    Sólo meses completos. `weighted_position_sum` = SUM(posición × impresiones),
    para recalcular la posición ponderada al juntar meses. PK con la consulta
    antes del mes: la lectura es "el historial de ESTA consulta".
    """
    __tablename__ = "gsc_query_monthly"
    __table_args__ = (
        CheckConstraint("EXTRACT(DAY FROM month) = 1", name="ck_gsc_query_monthly_first_day"),
        CheckConstraint("source IN ('google', 'engine')", name="ck_gsc_query_monthly_source"),
    )

    site_url = Column(String(255), primary_key=True)
    query = Column(Text, primary_key=True)
    month = Column(Date, primary_key=True)  # día 1 del mes
    clicks = Column(Integer, nullable=False)
    impressions = Column(Integer, nullable=False)
    weighted_position_sum = Column(Float, nullable=False)
    # 'google' = importado por The Agency (retención de 16 meses);
    # 'engine' = historial traído una vez de The Engine
    # (`scripts/import_engine_positions.py`): no caduca a los 16 meses, pero se
    # borra igual si la web deja de tener cliente activo o al purgar la cuenta.
    source = Column(String(16), nullable=False, default="google", server_default="google")


# ── Accesos (credenciales compartidas) ───────────────────────────────────────

CREDENTIAL_LOG_ACTIONS = ("reveal", "copy", "create", "update", "share", "delete")


class Credential(Base):
    """Un acceso compartido (WordPress del cliente, GA, herramientas…).

    La contraseña sólo existe cifrada (``encrypt_vault_secret``, prefijo ``v1:``;
    el CHECK impide guardar texto plano). Ningún listado la devuelve: sólo
    ``POST /api/credentials/{id}/reveal``, que deja rastro en el registro.
    Fuera del journal de Deshacer a propósito (ver ``change_journal._SPECS``).
    """
    __tablename__ = "credentials"
    __table_args__ = (
        CheckConstraint("secret_encrypted LIKE 'v1:%'", name="ck_credentials_secret_encrypted"),
        CheckConstraint("totp_encrypted IS NULL OR totp_encrypted LIKE 'v1:%'", name="ck_credentials_totp_encrypted"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(200), nullable=False)
    url = Column(String(500), nullable=True)
    username = Column(String(255), nullable=True)
    secret_encrypted = Column(Text, nullable=False)
    # Clave del autenticador (2FA) como enlace otpauth:// normalizado, cifrada
    # igual que la contraseña. Sólo sale convertida en código (`/totp`).
    totp_encrypted = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)
    client_id = Column(Integer, ForeignKey("clients.id", ondelete="SET NULL"), nullable=True, index=True)
    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class CredentialShare(Base):
    """Con quién se comparte un acceso. Los admins ven todos sin fila aquí."""
    __tablename__ = "credential_shares"

    credential_id = Column(Integer, ForeignKey("credentials.id", ondelete="CASCADE"), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True)


class CredentialAccessLog(Base):
    """Quién vio, copió o cambió un acceso y cuándo. Sobrevive al borrado del acceso
    (``credential_id`` pasa a NULL y queda ``credential_name``)."""
    __tablename__ = "credential_access_log"
    __table_args__ = (
        CheckConstraint(
            "action IN ('reveal','copy','create','update','share','delete','totp')",
            name="ck_credential_access_log_action",
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    credential_id = Column(Integer, ForeignKey("credentials.id", ondelete="SET NULL"), nullable=True)
    credential_name = Column(String(200), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    action = Column(String(16), nullable=False)
    detail = Column(String(500), nullable=True)
    at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


Index("ix_credential_access_log_credential_at", CredentialAccessLog.credential_id, CredentialAccessLog.at)


# ── Webs: disponibilidad (monitor de caídas) ─────────────────────────────────
# Fuera del journal de Deshacer: son datos de máquina (estado, sondeos, caídas) y
# un webhook cifrado. Lo guarda ``test_webs_quedan_fuera_del_journal``.


class WebUptimeTarget(Base):
    """Una URL de un cliente que se comprueba cada pocos minutos."""
    __tablename__ = "web_uptime_targets"
    __table_args__ = (UniqueConstraint("client_id", "url", name="uq_web_uptime_targets_client_url"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(Integer, ForeignKey("clients.id", ondelete="CASCADE"), nullable=False)
    url = Column(String(500), nullable=False)
    label = Column(String(120), nullable=True)
    is_active = Column(Boolean, nullable=False, server_default="true", default=True)
    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class WebUptimeState(Base):
    """Máquina de estados de un objetivo: qué vimos, cuántas veces y cuándo toca mirar."""
    __tablename__ = "web_uptime_state"
    __table_args__ = (
        CheckConstraint(
            "status IN ('unknown','up','suspect','down','blocked')", name="ck_web_uptime_state_status",
        ),
    )

    target_id = Column(Integer, ForeignKey("web_uptime_targets.id", ondelete="CASCADE"), primary_key=True)
    status = Column(String(16), nullable=False, server_default="unknown", default="unknown")
    status_since = Column(DateTime(timezone=True), nullable=True)
    consecutive_failures = Column(SmallInteger, nullable=False, server_default="0", default=0)
    consecutive_successes = Column(SmallInteger, nullable=False, server_default="0", default=0)
    failing_since = Column(DateTime(timezone=True), nullable=True)
    blocked_since = Column(DateTime(timezone=True), nullable=True)
    last_checked_at = Column(DateTime(timezone=True), nullable=True)
    last_outcome = Column(String(16), nullable=True)
    last_status_code = Column(Integer, nullable=True)
    last_error = Column(String(32), nullable=True)
    last_response_ms = Column(Integer, nullable=True)
    next_check_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


Index("ix_web_uptime_state_next_check", WebUptimeState.next_check_at)


class WebOutage(Base):
    """Una caída (o un bloqueo largo) confirmada, con su aviso a Slack como outbox."""
    __tablename__ = "web_outages"
    __table_args__ = (
        CheckConstraint("kind IN ('down','blocked')", name="ck_web_outages_kind"),
        CheckConstraint(
            "slack_down_status IN ('pending','sent','failed','skipped')", name="ck_web_outages_slack_down",
        ),
        CheckConstraint(
            "slack_recovery_status IS NULL OR slack_recovery_status IN ('pending','sent','failed','skipped')",
            name="ck_web_outages_slack_recovery",
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    target_id = Column(Integer, ForeignKey("web_uptime_targets.id", ondelete="CASCADE"), nullable=False)
    kind = Column(String(16), nullable=False)
    started_at = Column(DateTime(timezone=True), nullable=False)
    confirmed_at = Column(DateTime(timezone=True), nullable=False)
    ended_at = Column(DateTime(timezone=True), nullable=True)
    cause = Column(String(32), nullable=True)
    status_code = Column(Integer, nullable=True)
    slack_down_status = Column(String(16), nullable=False, server_default="pending", default="pending")
    slack_down_sent_at = Column(DateTime(timezone=True), nullable=True)
    slack_recovery_status = Column(String(16), nullable=True)
    slack_recovery_sent_at = Column(DateTime(timezone=True), nullable=True)
    slack_attempts = Column(SmallInteger, nullable=False, server_default="0", default=0)


Index("uq_web_outages_open", WebOutage.target_id, unique=True, postgresql_where=WebOutage.ended_at.is_(None))
Index("ix_web_outages_target_started", WebOutage.target_id, WebOutage.started_at)


class WebUptimeProbe(Base):
    """Cada comprobación programada (30 días). Las de "Probar ahora" no se guardan."""
    __tablename__ = "web_uptime_probes"
    __table_args__ = (
        CheckConstraint("outcome IN ('up','down','blocked')", name="ck_web_uptime_probes_outcome"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    target_id = Column(Integer, ForeignKey("web_uptime_targets.id", ondelete="CASCADE"), nullable=False)
    checked_at = Column(DateTime(timezone=True), nullable=False)
    outcome = Column(String(16), nullable=False)
    status_code = Column(Integer, nullable=True)
    error = Column(String(32), nullable=True)
    response_ms = Column(Integer, nullable=True)


Index("ix_web_uptime_probes_target_checked", WebUptimeProbe.target_id, WebUptimeProbe.checked_at)
Index("ix_web_uptime_probes_checked", WebUptimeProbe.checked_at)


class ClientWebSettings(Base):
    """Ajustes web de un cliente: su canal de Slack (webhook cifrado) y su User-Agent.

    El webhook sólo existe cifrado (``encrypt_vault_secret``, prefijo ``v1:``; el
    CHECK impide guardarlo en claro) y ninguna respuesta lo devuelve.
    """
    __tablename__ = "client_web_settings"
    __table_args__ = (
        CheckConstraint(
            "slack_webhook_url IS NULL OR slack_webhook_url LIKE 'v1:%'",
            name="ck_client_web_settings_webhook_encrypted",
        ),
        CheckConstraint(
            "digest_min_severity IS NULL OR digest_min_severity IN ('critical','warning','info')",
            name="ck_client_web_settings_digest_min_severity",
        ),
    )

    client_id = Column(Integer, ForeignKey("clients.id", ondelete="CASCADE"), primary_key=True)
    slack_webhook_url = Column(Text, nullable=True)
    slack_channel_hint = Column(String(100), nullable=True)
    slack_enabled = Column(Boolean, nullable=False, server_default="false", default=False)
    slack_revoked_at = Column(DateTime(timezone=True), nullable=True)
    downtime_to_slack = Column(Boolean, nullable=False, server_default="true", default=True)
    user_agent = Column(String(300), nullable=True)
    # ── Vigilancia de cambios (migración ``web_changes_v1``) ──
    # Se enciende por cliente (``web_changes_toggle_v1``): apagada, ni se barre,
    # ni avisa, ni cuenta en su estado. Sus URLs y su historial se quedan.
    changes_enabled = Column(Boolean, nullable=False, server_default="false", default=False)
    # Sin DEFAULT a propósito: NULL = el valor de ``services/web/capture_defaults.py``.
    # Así corregir un default en código corrige a todos los clientes que no lo
    # cambiaron (lección de Vigil: el DEFAULT de una columna se queda congelado).
    digest_min_severity = Column(String(16), nullable=True)
    default_content_selector = Column(String(500), nullable=True)
    default_ignore_selectors = Column(JSONB, nullable=True)
    default_ignore_regexes = Column(JSONB, nullable=True)
    max_concurrency = Column(SmallInteger, nullable=True)
    request_timeout_s = Column(SmallInteger, nullable=True)
    crawl_delay_ms = Column(Integer, nullable=True)
    sweep_weekdays = Column(JSONB, nullable=True)
    sweep_skip_dates = Column(JSONB, nullable=True)
    sweep_summary_to_slack = Column(Boolean, nullable=True)
    updated_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


# ── Webs: vigilancia de cambios (portado de Vigil, migración ``web_changes_v1``) ──
# EXCEPCIÓN a la convención de PK enteras: estas tablas usan UUID para que la
# importación de Vigil (fase 3) conserve sus ids (enlaces de Slack ya enviados,
# ``last_snapshot_id``, ``prev_snapshot_id``…). Fuera del journal de Deshacer:
# datos de máquina y revisiones (``test_cambios_web_quedan_fuera_del_journal``).

_WEB_SEVERITIES = "('critical','warning','info')"


def _uuid_pk():
    return Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
                  server_default=func.gen_random_uuid())


class WebWatch(Base):
    """Una URL de un cliente cuyos cambios se vigilan (SEO, texto, enlaces, HTML)."""
    __tablename__ = "web_watches"
    __table_args__ = (
        UniqueConstraint("client_id", "url", name="uq_web_watches_client_url"),
        CheckConstraint("source IN ('manual','bulk','sitemap','csv')", name="ck_web_watches_source"),
    )

    id = _uuid_pk()
    client_id = Column(Integer, ForeignKey("clients.id", ondelete="CASCADE"), nullable=False)
    url = Column(String(500), nullable=False)
    label = Column(String(200), nullable=True)
    is_active = Column(Boolean, nullable=False, server_default="true", default=True)
    # Archivada = fuera de la lista y del barrido, con su historial intacto.
    archived_at = Column(DateTime(timezone=True), nullable=True)
    watch_seo = Column(Boolean, nullable=False, server_default="true", default=True)
    watch_content = Column(Boolean, nullable=False, server_default="true", default=True)
    watch_links = Column(Boolean, nullable=False, server_default="false", default=False)
    watch_html = Column(Boolean, nullable=False, server_default="false", default=False)
    # NULL = hereda de ``client_web_settings`` (y ésta, de ``capture_defaults``).
    content_selector = Column(String(500), nullable=True)
    ignore_selectors = Column(JSONB, nullable=True)
    ignore_regexes = Column(JSONB, nullable=True)
    muted = Column(Boolean, nullable=False, server_default="false", default=False)
    source = Column(String(16), nullable=False, server_default="manual", default="manual")
    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    # "Comprobar ahora": la petición deja la marca y el job ``web_sweep`` la recoge.
    check_requested_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


Index("ix_web_watches_client_active", WebWatch.client_id, WebWatch.is_active)
Index("ix_web_watches_check_requested", WebWatch.check_requested_at,
      postgresql_where=WebWatch.check_requested_at.is_not(None))


class WebSweepRun(Base):
    """Un barrido de un cliente (programado o pedido a mano)."""
    __tablename__ = "web_sweep_runs"
    __table_args__ = (
        CheckConstraint("trigger IN ('scheduler','manual','api')", name="ck_web_sweep_runs_trigger"),
        CheckConstraint("status IN ('running','done','partial','failed')", name="ck_web_sweep_runs_status"),
    )

    id = _uuid_pk()
    client_id = Column(Integer, ForeignKey("clients.id", ondelete="CASCADE"), nullable=False)
    # Fecha civil de la agencia (Europe/Madrid): el programado es uno por día.
    run_date = Column(Date, nullable=False)
    trigger = Column(String(16), nullable=False, server_default="scheduler", default="scheduler")
    status = Column(String(16), nullable=False, server_default="running", default="running")
    started_at = Column(DateTime(timezone=True), nullable=False)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    watches_total = Column(Integer, nullable=False, server_default="0", default=0)
    watches_done = Column(Integer, nullable=False, server_default="0", default=0)
    watches_error = Column(Integer, nullable=False, server_default="0", default=0)
    changes_found = Column(Integer, nullable=False, server_default="0", default=0)
    notified_at = Column(DateTime(timezone=True), nullable=True)
    # no_procede | disabled | revoked | sent | failed | skipped_no_changes | summary_sent
    notify_status = Column(String(32), nullable=True)
    notify_error = Column(String(500), nullable=True)


# Sólo el PROGRAMADO es único por cliente y día (lección 0bis de Vigil): lo
# manual se repite tantas veces como haga falta.
Index("uq_web_sweep_runs_scheduler_day", WebSweepRun.client_id, WebSweepRun.run_date, unique=True,
      postgresql_where=WebSweepRun.trigger == "scheduler")
Index("ix_web_sweep_runs_client_started", WebSweepRun.client_id, WebSweepRun.started_at)
Index("ix_web_sweep_runs_started", WebSweepRun.started_at)


class WebSnapshot(Base):
    """Cuerpos de una captura. Sólo se escriben cuando algún hash cambió."""
    __tablename__ = "web_snapshots"

    id = _uuid_pk()
    watch_id = Column(UUID(as_uuid=True), ForeignKey("web_watches.id", ondelete="CASCADE"), nullable=False)
    client_id = Column(Integer, ForeignKey("clients.id", ondelete="CASCADE"), nullable=False)
    run_id = Column(UUID(as_uuid=True), ForeignKey("web_sweep_runs.id", ondelete="SET NULL"), nullable=True)
    captured_at = Column(DateTime(timezone=True), nullable=False)
    content_hash = Column(String(64), nullable=True)
    html_hash = Column(String(64), nullable=True)
    status_code = Column(Integer, nullable=True)
    byte_size = Column(Integer, nullable=True)
    # gzip. NULL = ese cuerpo no se guardó en esta captura.
    text_gz = Column(LargeBinary, nullable=True)
    html_gz = Column(LargeBinary, nullable=True)
    # Texto sin comprimir si cabe en 32 KB (el diff de la noche siguiente no descomprime).
    text_inline = Column(Text, nullable=True)
    is_pinned = Column(Boolean, nullable=False, server_default="false", default=False)


Index("ix_web_snapshots_watch_captured", WebSnapshot.watch_id, WebSnapshot.captured_at)


class WebWatchState(Base):
    """Estado ACTUAL de cada URL: hashes, última extracción y si se está mirando."""
    __tablename__ = "web_watch_state"

    watch_id = Column(UUID(as_uuid=True), ForeignKey("web_watches.id", ondelete="CASCADE"), primary_key=True)
    client_id = Column(Integer, ForeignKey("clients.id", ondelete="CASCADE"), nullable=False)
    last_checked_at = Column(DateTime(timezone=True), nullable=True)
    last_changed_at = Column(DateTime(timezone=True), nullable=True)
    last_status_code = Column(Integer, nullable=True)
    last_final_url = Column(Text, nullable=True)
    last_error = Column(String(500), nullable=True)
    consecutive_errors = Column(Integer, nullable=False, server_default="0", default=0)
    hash_seo = Column(String(64), nullable=True)
    hash_content = Column(String(64), nullable=True)
    hash_links = Column(String(64), nullable=True)
    hash_html = Column(String(64), nullable=True)
    # Última extracción normalizada = la "versión anterior" del diff.
    seo_json = Column(JSONB, nullable=True)
    links_json = Column(JSONB, nullable=True)
    needs_js_render = Column(Boolean, nullable=False, server_default="false", default=False)
    scope_missed = Column(Boolean, nullable=False, server_default="false", default=False)
    checking_since = Column(DateTime(timezone=True), nullable=True)
    last_snapshot_id = Column(UUID(as_uuid=True), ForeignKey("web_snapshots.id", ondelete="SET NULL"),
                              nullable=True)
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


Index("ix_web_watch_state_client_changed", WebWatchState.client_id, WebWatchState.last_changed_at)


class WebRunError(Base):
    """Sólo fallos de un barrido (una URL que no se pudo mirar, un host cortado)."""
    __tablename__ = "web_run_errors"

    id = _uuid_pk()
    run_id = Column(UUID(as_uuid=True), ForeignKey("web_sweep_runs.id", ondelete="CASCADE"), nullable=False)
    client_id = Column(Integer, ForeignKey("clients.id", ondelete="CASCADE"), nullable=False)
    watch_id = Column(UUID(as_uuid=True), ForeignKey("web_watches.id", ondelete="CASCADE"), nullable=True)
    kind = Column(String(32), nullable=False)
    message = Column(String(500), nullable=True)
    status_code = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


Index("ix_web_run_errors_run", WebRunError.run_id)


class WebChange(Base):
    """Un cambio detectado en una URL (uno por URL y barrido), con su revisión."""
    __tablename__ = "web_changes"
    __table_args__ = (
        UniqueConstraint("watch_id", "run_id", name="uq_web_changes_watch_run"),
        CheckConstraint(f"max_severity IN {_WEB_SEVERITIES}", name="ck_web_changes_max_severity"),
    )

    id = _uuid_pk()
    client_id = Column(Integer, ForeignKey("clients.id", ondelete="CASCADE"), nullable=False)
    watch_id = Column(UUID(as_uuid=True), ForeignKey("web_watches.id", ondelete="CASCADE"), nullable=False)
    # SET NULL, NO cascade: el histórico de cambios sobrevive a la retención de barridos.
    run_id = Column(UUID(as_uuid=True), ForeignKey("web_sweep_runs.id", ondelete="SET NULL"), nullable=True)
    snapshot_id = Column(UUID(as_uuid=True), ForeignKey("web_snapshots.id", ondelete="SET NULL"), nullable=True)
    prev_snapshot_id = Column(UUID(as_uuid=True), ForeignKey("web_snapshots.id", ondelete="SET NULL"),
                              nullable=True)
    max_severity = Column(String(16), nullable=False)
    detected_at = Column(DateTime(timezone=True), nullable=False)
    acknowledged_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    # Nombre de quien lo revisó: sobrevive al borrado del usuario y, en la
    # importación de Vigil, lleva el suyo cuando el email no casa con nadie.
    acknowledged_by_label = Column(String(120), nullable=True)
    acknowledged_at = Column(DateTime(timezone=True), nullable=True)
    note = Column(Text, nullable=True)


Index("ix_web_changes_client_detected", WebChange.client_id, WebChange.detected_at)
Index("ix_web_changes_watch_detected", WebChange.watch_id, WebChange.detected_at)
Index("ix_web_changes_pending", WebChange.client_id, WebChange.max_severity,
      postgresql_where=WebChange.acknowledged_at.is_(None))


class WebChangeItem(Base):
    """Detalle de un cambio: un item por campo que se movió."""
    __tablename__ = "web_change_items"
    __table_args__ = (
        CheckConstraint("kind IN ('seo','content','links','html','availability')",
                        name="ck_web_change_items_kind"),
        CheckConstraint(f"severity IN {_WEB_SEVERITIES}", name="ck_web_change_items_severity"),
    )

    id = _uuid_pk()
    change_id = Column(UUID(as_uuid=True), ForeignKey("web_changes.id", ondelete="CASCADE"), nullable=False)
    client_id = Column(Integer, ForeignKey("clients.id", ondelete="CASCADE"), nullable=False)
    kind = Column(String(16), nullable=False)
    field = Column(String(64), nullable=False)
    severity = Column(String(16), nullable=False)
    rule_code = Column(String(64), nullable=False)
    before_val = Column(Text, nullable=True)
    after_val = Column(Text, nullable=True)
    detail = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


Index("ix_web_change_items_change", WebChangeItem.change_id)


# ── Webs: salud diaria (migración ``web_health_v1``) ─────────────────────────
# Caducidad de certificado y dominio, robots.txt + sitemap y la revisión tras
# publicar de las tareas. Datos de máquina: fuera del journal de Deshacer.


class WebHostExpiry(Base):
    """Cuándo caducan el certificado TLS y el dominio de un host vigilado.

    Una fila por (cliente, host) de sus URLs de disponibilidad activas; el job
    ``web_health`` la reescribe a diario y borra las de hosts que ya no se miran.
    """
    __tablename__ = "web_host_expiry"
    __table_args__ = (
        CheckConstraint("cert_status IN ('ok','invalid','error','no_https')", name="ck_web_host_expiry_cert_status"),
        CheckConstraint(
            "domain_status IN ('ok','no_date','unsupported','not_found','error')",
            name="ck_web_host_expiry_domain_status",
        ),
    )

    client_id = Column(Integer, ForeignKey("clients.id", ondelete="CASCADE"), primary_key=True)
    host = Column(String(253), primary_key=True)
    checked_at = Column(DateTime(timezone=True), nullable=False)
    cert_status = Column(String(16), nullable=False)
    cert_expires_at = Column(DateTime(timezone=True), nullable=True)
    cert_issuer = Column(String(200), nullable=True)
    cert_error = Column(String(200), nullable=True)
    domain_name = Column(String(253), nullable=True)
    domain_status = Column(String(16), nullable=False)
    domain_expires_at = Column(DateTime(timezone=True), nullable=True)
    domain_error = Column(String(200), nullable=True)


class WebRobotsState(Base):
    """robots.txt y sitemap de un origen (``https://host``) de un cliente con la
    vigilancia de cambios encendida. Se guarda el último robots.txt (acotado), el
    anterior cuando cambia y si alguien revisó ese cambio."""
    __tablename__ = "web_robots_state"
    __table_args__ = (
        CheckConstraint("robots_status IN ('ok','missing','error')", name="ck_web_robots_state_status"),
        CheckConstraint(
            "sitemap_status IS NULL OR sitemap_status IN ('ok','empty','invalid','error')",
            name="ck_web_robots_state_sitemap_status",
        ),
        CheckConstraint(
            "sitemap_source IS NULL OR sitemap_source IN ('declared','default')",
            name="ck_web_robots_state_sitemap_source",
        ),
    )

    client_id = Column(Integer, ForeignKey("clients.id", ondelete="CASCADE"), primary_key=True)
    origin = Column(String(300), primary_key=True)
    checked_at = Column(DateTime(timezone=True), nullable=False)
    robots_status = Column(String(16), nullable=False)
    robots_error = Column(String(120), nullable=True)
    robots_hash = Column(String(64), nullable=True)
    robots_body = Column(Text, nullable=True)
    robots_blocks_all = Column(Boolean, nullable=False, server_default="false", default=False)
    robots_previous_body = Column(Text, nullable=True)
    robots_changed_at = Column(DateTime(timezone=True), nullable=True)
    robots_reviewed_at = Column(DateTime(timezone=True), nullable=True)
    robots_reviewed_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    sitemap_url = Column(String(500), nullable=True)
    sitemap_source = Column(String(16), nullable=True)
    sitemap_status = Column(String(16), nullable=True)
    sitemap_url_count = Column(Integer, nullable=True)
    sitemap_has_more = Column(Boolean, nullable=True)
    sitemap_error = Column(String(200), nullable=True)


class TaskPublishCheck(Base):
    """Revisión tras publicar: lo que vimos en el enlace de una tarea al completarla.

    Una fila por tarea (la última finalización). ``task_completed_at`` y ``url``
    dicen a qué finalización y a qué enlace corresponde: si la tarea se reabre y
    se vuelve a completar, o cambia el enlace, se comprueba de nuevo.
    """
    __tablename__ = "task_publish_checks"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','ok','problems','unreachable','skipped')", name="ck_task_publish_checks_status",
        ),
    )

    task_id = Column(Integer, ForeignKey("tasks.id", ondelete="CASCADE"), primary_key=True)
    url = Column(Text, nullable=False)
    task_completed_at = Column(DateTime, nullable=False)
    status = Column(String(16), nullable=False)
    attempts = Column(SmallInteger, nullable=False, server_default="0", default=0)
    next_attempt_at = Column(DateTime(timezone=True), nullable=True)
    checked_at = Column(DateTime(timezone=True), nullable=True)
    http_status = Column(Integer, nullable=True)
    final_url = Column(Text, nullable=True)
    error = Column(String(32), nullable=True)
    results = Column(JSONB, nullable=True)


Index("ix_task_publish_checks_pending", TaskPublishCheck.next_attempt_at,
      postgresql_where=TaskPublishCheck.status == "pending")
