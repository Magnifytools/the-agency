"""Seed script: creates initial users and task categories.

Run with: python -m backend.db.seed
"""
import asyncio
from sqlalchemy import select
from backend.db.database import engine, async_session
from backend.db.models import Base, User, TaskCategory, UserRole, ExpenseCategory, UserPermission
from backend.core.security import hash_password


USERS = [
    {
        "email": "david@magnify.ing",
        "full_name": "David Carrasco",
        "role": UserRole.admin,
        "hourly_rate": 50.0,
        "password": "Magnify2026!",
    },
    {
        "email": "nacho@magnify.ing",
        "full_name": "Nacho",
        "role": UserRole.member,
        "hourly_rate": 30.0,
        "password": "Magnify2026!",
    },
]

CATEGORIES = [
    {"name": "Auditoría SEO", "default_minutes": 120},
    {"name": "Keyword Research", "default_minutes": 90},
    {"name": "Optimización On-Page", "default_minutes": 60},
    {"name": "Link Building", "default_minutes": 45},
    {"name": "Contenido", "default_minutes": 60},
    {"name": "SEO Técnico", "default_minutes": 90},
    {"name": "Reporting", "default_minutes": 30},
    {"name": "Reunión Cliente", "default_minutes": 30},
]

EXPENSE_CATEGORIES = [
    {"name": "Software y herramientas", "description": "SaaS, licencias, suscripciones"},
    {"name": "Hosting y servidores", "description": "Cloud, dominio, CDN"},
    {"name": "Marketing y publicidad", "description": "Ads, campañas, patrocinios"},
    {"name": "Oficina y coworking", "description": "Alquiler, suministros"},
    {"name": "Subcontratación", "description": "Freelancers, agencias externas"},
    {"name": "Formación", "description": "Cursos, conferencias, libros"},
    {"name": "Impuestos y tasas", "description": "IVA, IS, IRPF, tasas administrativas"},
    {"name": "Otros gastos", "description": "Gastos no categorizados"},
]


async def seed():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with async_session() as session:
        # Seed users
        for u in USERS:
            existing = await session.execute(select(User).where(User.email == u["email"]))
            if existing.scalar_one_or_none() is None:
                user = User(
                    email=u["email"],
                    full_name=u["full_name"],
                    role=u["role"],
                    hourly_rate=u["hourly_rate"],
                    hashed_password=hash_password(u["password"]),
                )
                session.add(user)

        # Seed categories
        for c in CATEGORIES:
            existing = await session.execute(
                select(TaskCategory).where(TaskCategory.name == c["name"])
            )
            if existing.scalar_one_or_none() is None:
                session.add(TaskCategory(**c))

        # Seed expense categories
        for ec in EXPENSE_CATEGORIES:
            existing = await session.execute(
                select(ExpenseCategory).where(ExpenseCategory.name == ec["name"])
            )
            if existing.scalar_one_or_none() is None:
                session.add(ExpenseCategory(**ec))

        await session.commit()

        # Seed default permissions for member user
        member_result = await session.execute(
            select(User).where(User.email == "nacho@magnify.ing")
        )
        member = member_result.scalar_one_or_none()
        if member:
            existing_perms = await session.execute(
                select(UserPermission).where(UserPermission.user_id == member.id)
            )
            if not existing_perms.scalars().first():
                default_modules = [
                    "dashboard", "clients", "tasks", "projects", "timesheet",
                    "communications", "proposals", "reports", "growth", "digests",
                ]
                for module in default_modules:
                    session.add(UserPermission(
                        user_id=member.id,
                        module=module,
                        can_read=True,
                        can_write=True,
                    ))
                await session.commit()
                print(f"Default permissions created for member user ({len(default_modules)} modules)")

        print("Seed completed successfully.")


if __name__ == "__main__":
    asyncio.run(seed())
