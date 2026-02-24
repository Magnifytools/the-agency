import enum
from datetime import datetime

from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
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


class ProposalStatus(str, enum.Enum):
    draft = "draft"
    sent = "sent"
    accepted = "accepted"
    rejected = "rejected"


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
    is_active = Column(Boolean, nullable=False, default=True)
    invited_by = Column(Integer, ForeignKey("users.id"), nullable=True)

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

    tasks = relationship("Task", back_populates="client", lazy="selectin")
    projects = relationship("Project", back_populates="client", lazy="selectin")
    communications = relationship("CommunicationLog", back_populates="client", lazy="selectin", order_by="CommunicationLog.occurred_at.desc()")
    incomes = relationship("Income", back_populates="client", lazy="selectin")


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

    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False)

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

    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)

    project = relationship("Project", back_populates="phases", lazy="selectin")
    tasks = relationship("Task", back_populates="phase", lazy="selectin")


class Proposal(TimestampMixin, Base):
    __tablename__ = "proposals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(200), nullable=False)
    status = Column(Enum(ProposalStatus), nullable=False, default=ProposalStatus.draft)
    budget = Column(Float, nullable=True)
    scope = Column(Text, nullable=True)
    valid_until = Column(DateTime, nullable=True)

    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True)

    client = relationship("Client", lazy="selectin")
    project = relationship("Project", lazy="selectin")


class Event(TimestampMixin, Base):
    __tablename__ = "events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    event_type = Column(Enum(EventType), nullable=False, default=EventType.other)
    start_time = Column(DateTime, nullable=False)
    end_time = Column(DateTime, nullable=True)
    is_all_day = Column(Boolean, nullable=False, default=False)

    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    client = relationship("Client", lazy="selectin")
    project = relationship("Project", lazy="selectin")
    user = relationship("User", lazy="selectin")


class Task(TimestampMixin, Base):
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    status = Column(Enum(TaskStatus), nullable=False, default=TaskStatus.pending)
    estimated_minutes = Column(Integer, nullable=True)
    actual_minutes = Column(Integer, nullable=True)
    due_date = Column(DateTime, nullable=True)
    is_inbox = Column(Boolean, nullable=False, default=False)

    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False)
    category_id = Column(Integer, ForeignKey("task_categories.id"), nullable=True)
    assigned_to = Column(Integer, ForeignKey("users.id"), nullable=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True)
    phase_id = Column(Integer, ForeignKey("project_phases.id"), nullable=True)
    depends_on = Column(Integer, ForeignKey("tasks.id"), nullable=True)

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

    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    task = relationship("Task", back_populates="time_entries", lazy="selectin")
    user = relationship("User", lazy="selectin")


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

    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    client = relationship("Client", back_populates="communications", lazy="selectin")
    user = relationship("User", lazy="selectin")


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

    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True)
    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=True)

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

    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False)

    client = relationship("Client", lazy="selectin")


class InvoiceItem(TimestampMixin, Base):
    __tablename__ = "invoice_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    description = Column(String(255), nullable=False)
    quantity = Column(Float, nullable=False, default=1)
    unit_price = Column(Float, nullable=False)

    invoice_id = Column(Integer, ForeignKey("invoices.id"), nullable=False)
    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=True)

    invoice = relationship("Invoice", lazy="selectin")
    task = relationship("Task", lazy="selectin")


class AuditLog(TimestampMixin, Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    action = Column(String(50), nullable=False)
    entity_type = Column(String(50), nullable=False)
    entity_id = Column(Integer, nullable=False)
    details = Column(Text, nullable=True)

    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)

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

    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True)

    user = relationship("User", lazy="selectin")
    client = relationship("Client", lazy="selectin")
    project = relationship("Project", lazy="selectin")


class UserPermission(TimestampMixin, Base):
    __tablename__ = "user_permissions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
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
    invited_by = Column(Integer, ForeignKey("users.id"), nullable=False)
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
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True)
    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=True)

    project = relationship("Project", lazy="selectin")
    task = relationship("Task", lazy="selectin")


# --- Financial Models (ported from Gestor Financiero) ---

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
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True)
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
    category_id = Column(Integer, ForeignKey("expense_categories.id"), nullable=True)
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
    brief_id = Column(Integer, ForeignKey("advisor_ai_briefs.id"), nullable=False)
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
