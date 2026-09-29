from pydantic import BaseModel


class UsageWindow(BaseModel):
    days: int
    start: str
    end: str


class WorkContextMetrics(BaseModel):
    total: int
    with_project: int
    without_project: int
    coverage_percent: float | None


class WorkPlanningMetrics(BaseModel):
    total: int
    planned_or_waiting: int
    unplanned: int
    coverage_percent: float | None


class IncidentMetrics(BaseModel):
    active: int
    snoozed: int
    dismissed: int
    resolved_in_window: int


class DailyMetrics(BaseModel):
    updates: int
    authors: int
    user_days: int


class CommandChannelMetrics(BaseModel):
    app: int
    extension: int
    unknown: int


class CommandMetrics(BaseModel):
    executed: int
    failed: int
    needs_input: int
    needs_review: int
    undone: int
    terminal_total: int
    success_percent: float | None
    by_channel: CommandChannelMetrics


class DeliveryMetrics(BaseModel):
    sent: int
    failed: int
    uncertain: int
    expired: int
    cancelled: int
    pending: int
    sending: int
    terminal_total: int
    confirmation_percent: float | None


class OperationalUsageResponse(BaseModel):
    as_of: str
    window: UsageWindow
    work_context: WorkContextMetrics
    work_planning: WorkPlanningMetrics
    incidents: IncidentMetrics
    dailys: DailyMetrics
    commands: CommandMetrics
    deliveries: DeliveryMetrics
