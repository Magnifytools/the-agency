from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel

DailyFactKind = Literal[
    "task_completed", "time_logged", "task_advanced", "task_waiting", "next_step"
]


class DailyFact(BaseModel):
    key: str
    kind: DailyFactKind
    task_id: int | None = None
    title: str
    client_id: int | None = None
    client_name: str | None = None
    project_id: int | None = None
    project_name: str | None = None
    minutes: int | None = None
    href: str | None = None
    detail: str | None = None


class DailyFacts(BaseModel):
    date: date
    text: str
    completed_count: int
    worked_on_count: int
    total_minutes: int
    facts: list[DailyFact]
