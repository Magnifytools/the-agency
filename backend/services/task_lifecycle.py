"""State timestamps shared by interactive and automated task mutations."""
from backend.services.temporal import business_today, utc_now_naive
from backend.db.models import Task, TaskStatus


def stamp_task_status(task: Task, previous_status: TaskStatus | str | None = None) -> None:
    """Call after assigning a validated status; repeated completion keeps its date."""
    task.advanced_at = business_today() if task.status == TaskStatus.advanced else None
    if task.status == TaskStatus.completed and previous_status != TaskStatus.completed:
        task.completed_at = utc_now_naive()
    elif task.status != TaskStatus.completed and previous_status == TaskStatus.completed:
        task.completed_at = None
