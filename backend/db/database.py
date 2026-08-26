from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from backend.config import settings

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
    pool_recycle=1800,
)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db():
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()


# Los listeners del journal de cambios (Undo) se registran al importar el módulo.
# Va aquí y no en main.py para que cualquier código que abra una sesión los tenga
# puestos, incluidos scripts y tareas de fondo. Import al final para no chocar con
# la importación diferida que hace el propio journal de este módulo.
from backend.services import change_journal  # noqa: E402,F401
