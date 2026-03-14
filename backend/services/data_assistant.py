"""Data assistant — natural language queries over agency data using Claude."""
from __future__ import annotations

import logging
from datetime import date, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.services.ai_utils import get_anthropic_client

logger = logging.getLogger(__name__)

# Safe read-only tables the assistant can query
ALLOWED_TABLES = {
    "users", "clients", "tasks", "time_entries", "projects",
    "daily_updates", "leads", "proposals", "notifications",
}

SYSTEM_PROMPT = """Eres un asistente de datos para una agencia digital. Respondes preguntas sobre el equipo, clientes, tareas, horas y proyectos.

DATOS DISPONIBLES (esquema simplificado):
- users: id, full_name, email, role (admin/member), is_active, weekly_hours, created_at
- clients: id, name, status (active/paused/churned), monthly_budget, is_internal, created_at
- tasks: id, title, status (backlog/pending/in_progress/waiting/in_review/completed/cancelled), priority (urgent/high/medium/low), assigned_to (→users.id), client_id, project_id, estimated_minutes, due_date, scheduled_date, created_at
- time_entries: id, minutes, date, task_id (→tasks.id), user_id (→users.id), notes
- projects: id, name, client_id, status
- daily_updates: id, user_id, date, status (draft/sent), raw_text
- leads: id, company_name, status (new/contacted/qualified/proposal/negotiation/won/lost), assigned_to, estimated_value, next_followup_date
- proposals: id, lead_id, status, total_amount

REGLAS:
1. Responde en español, breve y directo.
2. Usa los datos del contexto que te paso, NO inventes números.
3. Si la pregunta no se puede responder con los datos disponibles, dilo claramente.
4. Formatea números: horas con 1 decimal, moneda con separador de miles.
5. Si hay que listar personas, muestra máximo 10 y di cuántas más hay.
6. Para "esta semana" usa lunes a hoy. Para "este mes" usa el 1ro al último día del mes actual.
"""


async def ask_assistant(question: str, db: AsyncSession) -> dict:
    """Process a natural language question about agency data.

    Gathers relevant context from the database, sends it to Claude,
    and returns the answer.
    """
    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    month_start = today.replace(day=1)

    # Gather context data based on keywords in the question
    context_parts: list[str] = []
    q_lower = question.lower()

    # Always include basic stats
    basic = await db.execute(text("""
        SELECT
            (SELECT COUNT(*) FROM users WHERE is_active = true) as active_users,
            (SELECT COUNT(*) FROM clients WHERE status = 'active') as active_clients,
            (SELECT COUNT(*) FROM tasks WHERE status NOT IN ('completed', 'cancelled')) as open_tasks,
            (SELECT COUNT(*) FROM tasks WHERE status = 'completed' AND created_at >= :month_start) as completed_this_month
    """), {"month_start": month_start})
    row = basic.mappings().first()
    if row:
        context_parts.append(f"Resumen: {row['active_users']} usuarios activos, {row['active_clients']} clientes activos, {row['open_tasks']} tareas abiertas, {row['completed_this_month']} completadas este mes.")

    # Hours context
    if any(w in q_lower for w in ["hora", "tiempo", "registr", "timesheet", "semana", "mes", "factur"]):
        hours = await db.execute(text("""
            SELECT u.full_name,
                   COALESCE(SUM(CASE WHEN te.date >= :week_start THEN te.minutes END), 0) as week_mins,
                   COALESCE(SUM(CASE WHEN te.date >= :month_start THEN te.minutes END), 0) as month_mins
            FROM users u
            LEFT JOIN time_entries te ON te.user_id = u.id AND te.date >= :month_start
            WHERE u.is_active = true
            GROUP BY u.id, u.full_name
            ORDER BY month_mins DESC
            LIMIT 15
        """), {"week_start": week_start, "month_start": month_start})
        rows = hours.mappings().all()
        lines = [f"  - {r['full_name']}: {round(r['month_mins']/60, 1)}h mes, {round(r['week_mins']/60, 1)}h semana" for r in rows]
        context_parts.append("Horas por persona:\n" + "\n".join(lines))

    # Client hours
    if any(w in q_lower for w in ["cliente", "client", "rentab", "presupuesto", "budget"]):
        clients = await db.execute(text("""
            SELECT c.name, c.monthly_budget,
                   COALESCE(SUM(te.minutes), 0) as month_mins,
                   COUNT(DISTINCT t.id) as task_count
            FROM clients c
            LEFT JOIN tasks t ON t.client_id = c.id
            LEFT JOIN time_entries te ON te.task_id = t.id AND te.date >= :month_start
            WHERE c.status = 'active' AND c.is_internal = false
            GROUP BY c.id, c.name, c.monthly_budget
            ORDER BY month_mins DESC
            LIMIT 15
        """), {"month_start": month_start})
        rows = clients.mappings().all()
        lines = [f"  - {r['name']}: {round(r['month_mins']/60, 1)}h ({r['task_count']} tareas, presupuesto: {r['monthly_budget'] or 'N/A'}€)" for r in rows]
        context_parts.append("Clientes este mes:\n" + "\n".join(lines))

    # Tasks context
    if any(w in q_lower for w in ["tarea", "task", "pendiente", "vencid", "atrasad", "carga", "asignad"]):
        tasks = await db.execute(text("""
            SELECT u.full_name,
                   COUNT(*) FILTER (WHERE t.status = 'in_progress') as in_progress,
                   COUNT(*) FILTER (WHERE t.status = 'pending') as pending,
                   COUNT(*) FILTER (WHERE t.due_date < :today AND t.status NOT IN ('completed', 'cancelled')) as overdue,
                   COALESCE(SUM(t.estimated_minutes) FILTER (WHERE t.status IN ('pending', 'in_progress')), 0) as est_minutes
            FROM users u
            LEFT JOIN tasks t ON t.assigned_to = u.id
            WHERE u.is_active = true
            GROUP BY u.id, u.full_name
            ORDER BY (in_progress + pending) DESC
            LIMIT 15
        """), {"today": today})
        rows = tasks.mappings().all()
        lines = [f"  - {r['full_name']}: {r['in_progress']} en curso, {r['pending']} pendientes, {r['overdue']} vencidas ({round(r['est_minutes']/60, 1)}h estimadas)" for r in rows]
        context_parts.append("Tareas por persona:\n" + "\n".join(lines))

    # Leads/pipeline
    if any(w in q_lower for w in ["lead", "pipeline", "propuesta", "venta", "comercial", "prospect"]):
        leads = await db.execute(text("""
            SELECT status, COUNT(*) as cnt, COALESCE(SUM(estimated_value), 0) as total_value
            FROM leads
            WHERE status NOT IN ('won', 'lost')
            GROUP BY status
            ORDER BY cnt DESC
        """))
        rows = leads.mappings().all()
        lines = [f"  - {r['status']}: {r['cnt']} leads ({r['total_value']}€)" for r in rows]
        context_parts.append("Pipeline de leads:\n" + "\n".join(lines))

    # Daily updates
    if any(w in q_lower for w in ["daily", "diario", "reporte", "actualización"]):
        dailys = await db.execute(text("""
            SELECT u.full_name, MAX(d.date) as last_daily,
                   COUNT(*) FILTER (WHERE d.date >= :week_start) as this_week
            FROM users u
            LEFT JOIN daily_updates d ON d.user_id = u.id
            WHERE u.is_active = true
            GROUP BY u.id, u.full_name
            ORDER BY last_daily DESC NULLS LAST
            LIMIT 15
        """), {"week_start": week_start})
        rows = dailys.mappings().all()
        lines = [f"  - {r['full_name']}: último {r['last_daily'] or 'nunca'}, {r['this_week']} esta semana" for r in rows]
        context_parts.append("Dailys por persona:\n" + "\n".join(lines))

    context = f"Fecha actual: {today.isoformat()}\nLunes de esta semana: {week_start.isoformat()}\n\n" + "\n\n".join(context_parts)

    # Call Claude
    client = get_anthropic_client()
    message = await client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=500,
        system=SYSTEM_PROMPT,
        messages=[
            {"role": "user", "content": f"CONTEXTO DE DATOS:\n{context}\n\nPREGUNTA: {question}"},
        ],
    )

    answer = message.content[0].text.strip()

    return {
        "question": question,
        "answer": answer,
        "model": message.model,
        "usage": {
            "input_tokens": message.usage.input_tokens,
            "output_tokens": message.usage.output_tokens,
        },
    }
