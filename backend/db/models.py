import enum
from datetime import datetime

from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    Numeric,
    Text,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Boolean,
    JSON,
    func,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)


# --- Enums ---

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


class TaskStatus(str, enum.Enum):
    pending = "pending"
    in_progress = "in_progress"
    completed = "completed"


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
    quality = "quality"


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


class ResourceType(str, enum.Enum):
    spreadsheet = "spreadsheet"
    document = "document"
    email = "email"
    account = "account"
    dashboard = "dashboard"
    other = "other"


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


# --- Models ---

class User(TimestampMixin, Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    full_name = Column(String(255), nullable=False)
    role = Column(Enum(UserRole), nullable=False, default=UserRole.member)
    hourly_rate = Column(Float, nullable=True)
    weekly_hours = Column(Float, nullable=False, default=40.0)
    is_active = Column(Boolean, nullable=False, default=True)
    invited_by = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)

    tasks = relationship("Task", back_populates="assigned_user", lazy="selectin", foreign_keys="[Task.assigned_to]")
    permissions = relationship("UserPermission", back_populates="user", lazy="selectin", cascade="all, delete-orphan")


class Client(TimestampMixin, Base):
    __tablename__ = "clients"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    email = Column(String(255), nullable=True)
    phone = Column(String(50), nullable=True)
    company = Column(String(255), nullable=True)
    website = Column(String(255), nullable=True)
    contract_type = Column(Enum(ContractType), nullable=False, default=ContractType.monthly)
    monthly_budget = Column(Float, nullable=True)
    status = Column(Enum(ClientStatus), nullable=False, default=ClientStatus.active)
    notes = Column(Text, nullable=True)
    # Financial fields (from GF)
    cif = Column(String(50), nullable=True)
    currency = Column(String(10), nullable=False, default="EUR")
    monthly_fee = Column(Float, nullable=True)
    # Holded integration
    holded_contact_id = Column(String(100), nullable=True)
    vat_number = Column(String(50), nullable=True)
    # Analytics settings
    ga4_property_id = Column(String(50), nullable=True)
    gsc_url = Column(String(255), nullable=True)
    # Billing settings
    billing_cycle = Column(Enum(BillingCycle), nullable=True)
    billing_day = Column(Integer, nullable=True)  # 1-28
    next_invoice_date = Column(Date, nullable=True)
    last_invoiced_date = Column(Date, nullable=True)
    engine_project_id = Column(Integer, nullable=True)

    tasks = relationship("Task", back_populates="client", lazy="selectin")
    projects = relationship("Project", back_populates="client", lazy="selectin")
    communications = relationship("CommunicationLog", back_populates="client", lazy="selectin", order_by="CommunicationLog.occurred_at.desc()")
    contacts = relationship("ClientContact", back_populates="client", lazy="selectin", order_by="ClientContact.is_primary.desc()")
    incomes = relationship("Income", back_populates="client", lazy="selectin")
    resources = relationship("ClientResource", back_populates="client", lazy="selectin", order_by="ClientResource.label")
    billing_events = relationship("BillingEvent", back_populates="client", lazy="selectin", order_by="BillingEvent.event_date.desc()")


class TaskCategory(TimestampMixin, Base):
    __tablename__ = "task_categories"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False, unique=True)
    default_minutes = Column(Integer, nullable=False, default=60)

    tasks = relationship("Task", back_populates="category", lazy="selectin")


class Project(TimestampMixin, Base):
    __tablename__ = "projects"

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
    budget_amount = Column(Float, nullable=True)
    gsc_url = Column(String(255), nullable=True)
    ga4_property_id = Column(String(50), nullable=True)
    is_recurring = Column(Boolean, nullable=False, default=False)
    engine_project_id = Column(Integer, nullable=True)

    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)

    client = relationship("Client", back_populates="projects", lazy="selectin")
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
    budget = Column(Float, nullable=True)
    scope = Column(Text, nullable=True)

    # Relaciones
    lead = relationship("Lead", lazy="selectin")
    client = relationship("Client", lazy="selectin")
    created_by_user = relationship("User", lazy="selectin")
    converted_project = relationship("Project", foreign_keys=[converted_project_id], lazy="selectin")


class Event(TimestampMixin, Base):
    __tablename__ = "events"

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

    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    category_id = Column(Integer, ForeignKey("task_categories.id"), nullable=True, index=True)
    assigned_to = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True, index=True)
    phase_id = Column(Integer, ForeignKey("project_phases.id"), nullable=True, index=True)
    depends_on = Column(Integer, ForeignKey("tasks.id"), nullable=True, index=True)

    client = relationship("Client", back_populates="tasks", lazy="selectin")
    category = relationship("TaskCategory", back_populates="tasks", lazy="selectin")
    assigned_user = relationship("User", back_populates="tasks", lazy="selectin")
    time_entries = relationship("TimeEntry", back_populates="task", lazy="selectin")
    project = relationship("Project", back_populates="tasks", lazy="selectin")
    phase = relationship("ProjectPhase", back_populates="tasks", lazy="selectin")
    dependency = relationship("Task", remote_side="Task.id", lazy="selectin")


class TimeEntry(TimestampMixin, Base):
    __tablename__ = "time_entries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    minutes = Column(Integer, nullable=True)  # null = timer running
    started_at = Column(DateTime, nullable=True)  # set when timer starts
    date = Column(DateTime, nullable=False, default=func.now())
    notes = Column(Text, nullable=True)

    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    task = relationship("Task", back_populates="time_entries", lazy="selectin")
    user = relationship("User", lazy="selectin")


class ClientContact(TimestampMixin, Base):
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


class ClientResource(TimestampMixin, Base):
    __tablename__ = "client_resources"

    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    label = Column(String(200), nullable=False)
    url = Column(String(500), nullable=False)
    resource_type = Column(Enum(ResourceType), nullable=False, default=ResourceType.other)
    notes = Column(Text, nullable=True)

    client = relationship("Client", back_populates="resources", lazy="selectin")


class BillingEvent(TimestampMixin, Base):
    __tablename__ = "billing_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    event_type = Column(Enum(BillingEventType), nullable=False)
    amount = Column(Float, nullable=True)
    invoice_number = Column(String(100), nullable=True)
    notes = Column(Text, nullable=True)
    event_date = Column(Date, nullable=False)

    client = relationship("Client", back_populates="billing_events", lazy="selectin")


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
    amount = Column(Float, nullable=False)
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
    unit_price = Column(Float, nullable=False)

    invoice_id = Column(Integer, ForeignKey("invoices.id"), nullable=False, index=True)
    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=True, index=True)

    invoice = relationship("Invoice", lazy="selectin")
    task = relationship("Task", lazy="selectin")


class AuditLog(TimestampMixin, Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    action = Column(String(50), nullable=False)
    entity_type = Column(String(50), nullable=False)
    entity_id = Column(Integer, nullable=False)
    details = Column(Text, nullable=True)

    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    user = relationship("User", lazy="selectin")


class MonthlyClose(TimestampMixin, Base):
    __tablename__ = "monthly_closes"

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
    responsible_name = Column(String, nullable=False, default="")
    notes = Column(Text, nullable=False, default="")


class FinancialSettings(TimestampMixin, Base):
    __tablename__ = "financial_settings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tax_reserve = Column(Float, nullable=False, default=0)
    credit_limit = Column(Float, nullable=False, default=0)
    credit_used = Column(Float, nullable=False, default=0)
    monthly_close_day = Column(Integer, nullable=False, default=5)
    credit_alert_pct = Column(Float, nullable=False, default=70)
    tax_reserve_target_pct = Column(Float, nullable=False, default=20)
    # GF fields
    default_vat_rate = Column(Float, nullable=False, default=21.0)
    corporate_tax_rate = Column(Float, nullable=False, default=25.0)
    irpf_retention_rate = Column(Float, nullable=False, default=15.0)
    cash_start = Column(Float, nullable=False, default=0.0)
    # Advisor thresholds
    advisor_expense_alert_pct = Column(Float, nullable=False, default=20.0)
    advisor_margin_warning_pct = Column(Float, nullable=False, default=10.0)
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


class GeneratedReport(TimestampMixin, Base):
    __tablename__ = "generated_reports"

    id = Column(Integer, primary_key=True, autoincrement=True)
    report_type = Column(Enum(ReportType), nullable=False)
    title = Column(String(200), nullable=False)
    generated_at = Column(DateTime, nullable=False)
    period_start = Column(DateTime, nullable=True)
    period_end = Column(DateTime, nullable=True)
    content = Column(Text, nullable=False)  # JSON string with sections and summary

    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True, index=True)

    user = relationship("User", lazy="selectin")
    client = relationship("Client", lazy="selectin")
    project = relationship("Project", lazy="selectin")


class UserPermission(TimestampMixin, Base):
    __tablename__ = "user_permissions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    module = Column(String(50), nullable=False)
    can_read = Column(Boolean, nullable=False, default=True)
    can_write = Column(Boolean, nullable=False, default=False)

    user = relationship("User", back_populates="permissions", lazy="selectin")


class UserInvitation(TimestampMixin, Base):
    __tablename__ = "user_invitations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String(255), nullable=False)
    token = Column(String(255), unique=True, nullable=False, index=True)
    role = Column(Enum(UserRole), nullable=False, default=UserRole.member)
    invited_by = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    expires_at = Column(DateTime, nullable=False)
    accepted_at = Column(DateTime, nullable=True)

    inviter = relationship("User", lazy="selectin")


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


# --- Financial Models (ported from Gestor Financiero) ---

class WeeklyDigest(TimestampMixin, Base):
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

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(Date, nullable=False)
    description = Column(String(255), nullable=False)
    amount = Column(Float, nullable=False)
    type = Column(String(50), nullable=False, default="factura")  # factura, recurrente, extra
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True, index=True)
    invoice_number = Column(String(100), nullable=False, default="")
    vat_rate = Column(Float, nullable=False, default=21.0)
    vat_amount = Column(Float, nullable=False, default=0.0)
    status = Column(String(50), nullable=False, default="cobrado")  # pendiente, cobrado
    notes = Column(Text, nullable=False, default="")

    client = relationship("Client", back_populates="incomes", lazy="selectin")


class Expense(TimestampMixin, Base):
    __tablename__ = "expenses"

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(Date, nullable=False)
    description = Column(String(255), nullable=False)
    amount = Column(Float, nullable=False)
    category_id = Column(Integer, ForeignKey("expense_categories.id"), nullable=True, index=True)
    is_recurring = Column(Boolean, nullable=False, default=False)
    recurrence_period = Column(String(50), nullable=False, default="")  # mensual, trimestral, anual
    vat_rate = Column(Float, nullable=False, default=21.0)
    vat_amount = Column(Float, nullable=False, default=0.0)
    is_deductible = Column(Boolean, nullable=False, default=True)
    supplier = Column(String(255), nullable=False, default="")
    notes = Column(Text, nullable=False, default="")

    category = relationship("ExpenseCategory", back_populates="expenses", lazy="selectin")


class Tax(TimestampMixin, Base):
    __tablename__ = "taxes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    model = Column(String(50), nullable=False, default="")  # 303, 200, 111, 115
    period = Column(String(50), nullable=False, default="")  # Q1, Q2, Q3, Q4, anual
    year = Column(Integer, nullable=False)
    base_amount = Column(Float, nullable=False, default=0.0)
    tax_rate = Column(Float, nullable=False, default=0.0)
    tax_amount = Column(Float, nullable=False, default=0.0)
    status = Column(String(50), nullable=False, default="pendiente")  # pendiente, pagado, aplazado
    due_date = Column(Date, nullable=True)
    paid_date = Column(Date, nullable=True)
    notes = Column(Text, nullable=False, default="")


class Forecast(TimestampMixin, Base):
    __tablename__ = "forecasts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    month = Column(Date, nullable=False)
    projected_income = Column(Float, nullable=False, default=0.0)
    projected_expenses = Column(Float, nullable=False, default=0.0)
    projected_taxes = Column(Float, nullable=False, default=0.0)
    projected_profit = Column(Float, nullable=False, default=0.0)
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
    auto_daily_summary = Column(Boolean, default=False)
    summary_time = Column(String(5), default="18:00")  # HH:MM
    include_ai_note = Column(Boolean, default=True)
    last_sent_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())


# ── Daily Updates ─────────────────────────────────────


class DailyUpdate(TimestampMixin, Base):
    __tablename__ = "daily_updates"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    date = Column(Date, nullable=False)
    raw_text = Column(Text, nullable=False)
    parsed_data = Column(JSON, nullable=True)  # {projects: [{name, client, tasks: [{description, details}]}]}
    status = Column(Enum(DailyUpdateStatus), nullable=False, default=DailyUpdateStatus.draft)
    discord_sent_at = Column(DateTime, nullable=True)

    user = relationship("User", lazy="selectin")


class Notification(TimestampMixin, Base):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    type = Column(String(50), nullable=False)  # task_assigned, task_overdue, lead_followup, digest_pending
    title = Column(String(255), nullable=False)
    message = Column(Text, nullable=True)
    is_read = Column(Boolean, nullable=False, default=False)
    link_url = Column(String(500), nullable=True)  # e.g. "/tasks?id=123"
    entity_type = Column(String(50), nullable=True)  # task, lead, digest
    entity_id = Column(Integer, nullable=True)

    user = relationship("User", lazy="selectin")
