"""Seed script: creates initial users and task categories.

Run with: python -m backend.db.seed

Passwords are read from environment variables:
  SEED_ADMIN_PASSWORD  — password for the admin user (david@magnify.ing)
  SEED_MEMBER_PASSWORD — password for the member user (nacho@magnify.ing)

If not set, random 24-char passwords are generated and printed to stdout.
"""
import asyncio
import os
import secrets
import string
from sqlalchemy import select
from backend.db.database import engine, async_session
from backend.db.models import Base, User, TaskCategory, UserRole, ExpenseCategory, UserPermission, ServiceTemplate, ServiceType
from backend.core.security import hash_password


def _generate_password(length: int = 24) -> str:
    alphabet = string.ascii_letters + string.digits + "!@#$%&*"
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _get_seed_users() -> list[dict]:
    admin_pw = os.environ.get("SEED_ADMIN_PASSWORD") or _generate_password()
    member_pw = os.environ.get("SEED_MEMBER_PASSWORD") or _generate_password()

    if not os.environ.get("SEED_ADMIN_PASSWORD"):
        print(f"⚠ SEED_ADMIN_PASSWORD not set. Generated: {admin_pw}")
    if not os.environ.get("SEED_MEMBER_PASSWORD"):
        print(f"⚠ SEED_MEMBER_PASSWORD not set. Generated: {member_pw}")

    return [
        {
            "email": "david@magnify.ing",
            "full_name": "David Carrasco",
            "role": UserRole.admin,
            "hourly_rate": 50.0,
            "password": admin_pw,
        },
        {
            "email": "nacho@magnify.ing",
            "full_name": "Nacho",
            "role": UserRole.member,
            "hourly_rate": 30.0,
            "password": member_pw,
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


SERVICE_TEMPLATES = [
    {
        "service_type": ServiceType.seo_sprint,
        "name": "SEO Sprint — Puesta a punto",
        "description": "Proyecto intensivo de 3 meses para poner en orden el SEO del cliente: technical fixes, on-page, estructura y quick wins.",
        "is_recurring": False,
        "price_range_min": 3000,
        "price_range_max": 6000,
        "default_phases": [
            {"name": "Audit & Quick Wins", "duration": "Mes 1", "outcome": "Technical fixes implementados, sitemap optimizado, errores criticos resueltos."},
            {"name": "On-Page & Contenido", "duration": "Mes 2", "outcome": "Titles, metas, headings y contenido principal optimizado para keywords objetivo."},
            {"name": "Estructura & Entrega", "duration": "Mes 3", "outcome": "Arquitectura de informacion mejorada, internal linking optimizado, roadmap de continuidad entregado."},
        ],
        "default_includes": "Audit tecnico completo, keyword research, optimizacion on-page de paginas clave, configuracion de Search Console y Analytics, informe final con roadmap.",
        "default_excludes": "Creacion de contenido nuevo, link building externo, desarrollo web, mantenimiento post-proyecto.",
        "prompt_context": "SEO Sprint es un proyecto acotado de 3 meses para empresas que necesitan poner orden en su SEO. No es un retainer: tiene inicio, fin y entregables claros. El cliente se queda con un sitio web optimizado y un roadmap para seguir por su cuenta o contratar un retainer.",
    },
    {
        "service_type": ServiceType.migration,
        "name": "Supervision de Migracion Web",
        "description": "Acompanamiento tecnico durante una migracion de dominio, rediseno o cambio de plataforma para preservar el SEO.",
        "is_recurring": False,
        "price_range_min": 2000,
        "price_range_max": 8000,
        "default_phases": [
            {"name": "Pre-migracion", "duration": "2-4 semanas", "outcome": "Inventario de URLs, mapa de redirecciones, checklist tecnico preparado."},
            {"name": "Migracion", "duration": "1-2 semanas", "outcome": "Supervision del lanzamiento, validacion de redirecciones, monitoring en tiempo real."},
            {"name": "Post-migracion", "duration": "4 semanas", "outcome": "Monitoring de indexacion, correccion de errores, informe de impacto."},
        ],
        "default_includes": "Audit pre-migracion, mapa de redirecciones 301, checklist tecnico, supervision del lanzamiento, monitoring post-migracion durante 1 mes.",
        "default_excludes": "Desarrollo web, implementacion de redirecciones (responsabilidad del equipo de desarrollo), creacion de contenido.",
        "prompt_context": "Supervision de migracion web es un servicio critico. Una migracion mal hecha puede destruir anos de posicionamiento. Magnify supervisa todo el proceso para que el cliente no pierda trafico. El tono debe transmitir urgencia y expertise tecnico.",
    },
    {
        "service_type": ServiceType.market_study,
        "name": "Estudio Estrategico de Mercado SEO",
        "description": "Analisis profundo del mercado digital del cliente: competidores, oportunidades de keywords, gaps de contenido y plan de accion.",
        "is_recurring": False,
        "price_range_min": 2500,
        "price_range_max": 5000,
        "default_phases": [
            {"name": "Research & Analisis", "duration": "2 semanas", "outcome": "Mapa competitivo completo, keyword universe, analisis de SERPs."},
            {"name": "Estrategia", "duration": "1 semana", "outcome": "Documento estrategico con oportunidades priorizadas y plan de accion."},
            {"name": "Presentacion", "duration": "1 sesion", "outcome": "Sesion de presentacion con el equipo directivo y Q&A."},
        ],
        "default_includes": "Analisis de 5-10 competidores, keyword research extensivo, analisis de gaps de contenido, documento estrategico, sesion de presentacion.",
        "default_excludes": "Implementacion de la estrategia, creacion de contenido, optimizacion tecnica.",
        "prompt_context": "El estudio de mercado SEO es el primer paso para empresas que quieren entender su posicion en el mercado digital. Es un entregable de alto valor estrategico que suele preceder a un proyecto o retainer. El tono debe ser consultivo y orientado a negocio.",
    },
    {
        "service_type": ServiceType.consulting_retainer,
        "name": "Consultoria SEO Estrategica",
        "description": "Retainer mensual de consultoria SEO para empresas que tienen equipo interno pero necesitan direccion estrategica y expertise tecnico.",
        "is_recurring": True,
        "price_range_min": 1500,
        "price_range_max": 3000,
        "default_phases": [
            {"name": "Onboarding", "duration": "Mes 1", "outcome": "Audit inicial, definicion de KPIs, plan trimestral, accesos configurados."},
            {"name": "Ejecucion recurrente", "duration": "Mensual", "outcome": "Analisis, recomendaciones, seguimiento de implementacion, reporting."},
        ],
        "default_includes": "Reunion mensual de estrategia, recomendaciones tecnicas y de contenido, revision de implementaciones, reporting mensual, acceso a canal directo de comunicacion.",
        "default_excludes": "Implementacion directa de cambios, creacion de contenido, link building, desarrollo web.",
        "prompt_context": "La consultoria SEO es para empresas que ya tienen equipo (marketing, desarrollo) pero necesitan un experto externo que les guie. Magnify actua como el 'cerebro SEO' del equipo. El tono debe ser de partnership y confianza.",
    },
    {
        "service_type": ServiceType.partnership_retainer,
        "name": "Partnership SEO Integral",
        "description": "Retainer premium donde Magnify se integra como departamento SEO del cliente, ejecutando la estrategia completa.",
        "is_recurring": True,
        "price_range_min": 3000,
        "price_range_max": 8000,
        "default_phases": [
            {"name": "Onboarding", "duration": "Mes 1", "outcome": "Audit completo, estrategia anual, plan trimestral detallado, integracion con equipo."},
            {"name": "Ejecucion recurrente", "duration": "Mensual", "outcome": "Optimizacion continua, contenido, technical SEO, link building, reporting."},
        ],
        "default_includes": "Estrategia SEO completa, optimizacion tecnica continua, coordinacion de contenido, link building, reporting avanzado, reuniones semanales o quincenales, acceso prioritario.",
        "default_excludes": "Desarrollo web complejo, rediseno de sitio, paid media, social media management.",
        "prompt_context": "Partnership SEO es el servicio premium de Magnify. El cliente nos trata como su departamento SEO. Ejecutamos todo: estrategia, tecnico, contenido y off-page. El tono debe ser de compromiso total y resultados.",
    },
    {
        "service_type": ServiceType.brand_audit,
        "name": "Brand Visibility Audit",
        "description": "Analisis de la visibilidad de marca online del cliente: presencia en SERPs, share of voice, brand mentions y reputacion digital.",
        "is_recurring": False,
        "price_range_min": 1500,
        "price_range_max": 3000,
        "default_phases": [
            {"name": "Data Collection", "duration": "1 semana", "outcome": "Datos de brand search, SERPs de marca, mentions, competitor brands."},
            {"name": "Analisis & Report", "duration": "1 semana", "outcome": "Informe completo de visibilidad de marca con oportunidades identificadas."},
        ],
        "default_includes": "Analisis de brand SERPs, share of voice vs competidores, analisis de mentions, recomendaciones de mejora, documento ejecutivo.",
        "default_excludes": "Implementacion de mejoras, gestion de reputacion online, PR digital.",
        "prompt_context": "Brand Visibility Audit es un servicio de analisis rapido y de alto impacto. Ideal para directores de marketing que necesitan entender como se percibe su marca online. El entregable es visual, ejecutivo y accionable.",
    },
]


async def seed():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with async_session() as session:
        # Seed users
        users = _get_seed_users()
        for u in users:
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

        # Sync permissions for member user (always update to desired set)
        member_result = await session.execute(
            select(User).where(User.email == "nacho@magnify.ing")
        )
        member = member_result.scalar_one_or_none()
        if member:
            desired_modules = [
                "dashboard", "clients", "tasks", "projects", "timesheet",
            ]

            existing_perms = await session.execute(
                select(UserPermission).where(UserPermission.user_id == member.id)
            )
            existing = {p.module: p for p in existing_perms.scalars().all()}
            existing_modules = set(existing.keys())
            desired_set = set(desired_modules)

            # Remove permissions no longer desired
            removed = existing_modules - desired_set
            for mod in removed:
                await session.delete(existing[mod])

            # Add missing permissions
            added = desired_set - existing_modules
            for mod in added:
                session.add(UserPermission(
                    user_id=member.id,
                    module=mod,
                    can_read=True,
                    can_write=True,
                ))

            await session.commit()
            if removed or added:
                print(f"Member permissions synced: +{len(added)} added, -{len(removed)} removed → {len(desired_modules)} modules")
            else:
                print(f"Member permissions already up to date ({len(desired_modules)} modules)")

        # Seed service templates
        for tmpl_data in SERVICE_TEMPLATES:
            existing = await session.execute(
                select(ServiceTemplate).where(ServiceTemplate.service_type == tmpl_data["service_type"])
            )
            if existing.scalar_one_or_none() is None:
                session.add(ServiceTemplate(**tmpl_data))
        await session.commit()
        print(f"Service templates seeded ({len(SERVICE_TEMPLATES)} templates)")

        print("Seed completed successfully.")


if __name__ == "__main__":
    asyncio.run(seed())
