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
# Sesión global (la base de `settings.DATABASE_URL`). Quien la use desde una
# petición (middleware, rutas que lanzan jobs) debe leerla en el momento de
# usarla (`database.async_session` o un import dentro de la función), nunca con
# un `from ... import async_session` a nivel de módulo: así los tests pueden
# sustituirla y nunca escriben en la base de `.env` (ver tests/conftest.py).
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
