"""State timestamps shared by interactive and automated task mutations."""
from datetime import date, datetime, timezone
from backend.db.models import Task, TaskStatus


def stamp_task_status(task: Task, previous_status: TaskStatus | str | None = None) -> None:
    """Call after assigning a validated status; repeated completion keeps its date."""
    task.advanced_at = date.today() if task.status == TaskStatus.advanced else None
    if task.status == TaskStatus.completed and previous_status != TaskStatus.completed:
        task.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
    elif task.status != TaskStatus.completed and previous_status == TaskStatus.completed:
        task.completed_at = None
