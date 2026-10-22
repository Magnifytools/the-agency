"""Los tests nunca abren la base de `.env` y el código de las peticiones lee la
sesión global en el momento de usarla (si no, los tests no podrían sustituirla)."""
import ast
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]


async def test_usar_la_sesion_global_en_un_test_es_un_error():
    from sqlalchemy import text
    from sqlalchemy.exc import UnboundExecutionError

    from backend.db import database

    async with database.async_session() as session:  # crearla sí se puede
        with pytest.raises(UnboundExecutionError):
            await session.execute(text("SELECT 1"))


def _module_level_imports_of_async_session(path: Path) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:  # sólo nivel de módulo
        if isinstance(node, ast.ImportFrom) and node.module == "backend.db.database":
            if any(alias.name == "async_session" for alias in node.names):
                return True
    return False


def test_las_peticiones_no_capturan_la_sesion_global_al_importar():
    files = [BACKEND / "main.py", *sorted((BACKEND / "api").rglob("*.py"))]
    offenders = [str(p.relative_to(BACKEND)) for p in files if _module_level_imports_of_async_session(p)]
    assert offenders == [], (
        "Usa `from backend.db import database` y `database.async_session` (o un import "
        f"dentro de la función): {offenders}"
    )
