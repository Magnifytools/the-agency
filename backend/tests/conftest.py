import os
import sys
from unittest.mock import MagicMock, AsyncMock

# ── Todos los módulos activos durante los tests ─────────────────────
# En producción hay 20 módulos ocultos (backend/core/modules.py): su router no
# se registra. Pero el código sigue en el repositorio y la idea es poder
# reactivarlos, así que la suite corre con TODO activado: si algo se pudre
# mientras está oculto, queremos enterarnos ahora y no el día que se reactive.
#
# La configuración real de producción se verifica aparte, en
# tests/test_hidden_modules.py, levantando la app en un subproceso limpio.
#
# Tiene que ir ANTES de importar backend.main: el registro de routers se
# resuelve en tiempo de importación.
os.environ.setdefault("AGENCY_HIDDEN_MODULES", "")

# ── Mock asyncpg before anything imports database.py ────────────────
# The system Python may not have asyncpg installed (it runs inside Docker).
# We mock the engine so tests can import the FastAPI app without a real DB.
if "asyncpg" not in sys.modules:
    sys.modules["asyncpg"] = MagicMock()

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import AsyncClient, ASGITransport  # noqa: E402

from backend.main import app  # noqa: E402
from backend.api.deps import get_current_user  # noqa: E402
from backend.db.database import get_db  # noqa: E402
from backend.db.models import User, UserRole, UserPermission  # noqa: E402


def _make_admin():
    user = MagicMock(spec=User)
    user.id = 1
    user.email = "admin@test.com"
    user.full_name = "Admin Test"
    user.role = UserRole.admin
    user.is_active = True
    user.hourly_rate = 40.0
    user.weekly_hours = 40.0
    user.preferences = None
    user.region = None
    user.locality = None
    user.short_name = None
    user.birthday = None
    user.job_title = None
    user.morning_reminder_time = "09:00"
    user.evening_reminder_time = "18:00"
    user.onboarding_completed = True
    user.google_calendar_connected = False
    user.google_refresh_token = None
    user.google_calendar_id = None
    user.google_calendar_synced_at = None
    user.permissions = []
    return user


def _make_member():
    user = MagicMock(spec=User)
    user.id = 2
    user.email = "member@test.com"
    user.full_name = "Member Test"
    user.role = UserRole.member
    user.is_active = True
    user.hourly_rate = 30.0
    user.weekly_hours = 40.0
    user.preferences = None
    user.region = None
    user.locality = None
    user.short_name = None
    user.birthday = None
    user.job_title = None
    user.morning_reminder_time = "09:00"
    user.evening_reminder_time = "18:00"
    user.onboarding_completed = False
    perm = MagicMock(spec=UserPermission)
    perm.module = "clients"
    perm.can_read = True
    perm.can_write = False
    user.permissions = [perm]
    return user


@pytest.fixture
def admin_user():
    return _make_admin()


@pytest.fixture
def member_user():
    return _make_member()


def _make_mock_db():
    """AsyncMock DB where execute() returns a MagicMock (not AsyncMock).

    AsyncMock child attributes are also AsyncMock — calling them returns
    un-awaited coroutines, causing serialization errors in routes that do
    `result.scalar()` or `result.scalars().all()`. Using MagicMock for the
    execute return value avoids that.
    """
    mock_db = AsyncMock()
    mock_db.add = MagicMock()  # db.add() is sync, not async
    execute_result = MagicMock()
    execute_result.scalar.return_value = 0
    execute_result.scalar_one_or_none.return_value = None
    execute_result.scalars.return_value.all.return_value = []
    execute_result.scalars.return_value.first.return_value = None
    mock_db.execute.return_value = execute_result
    return mock_db


@pytest_asyncio.fixture
async def admin_client(admin_user):
    mock_db = _make_mock_db()

    app.dependency_overrides[get_current_user] = lambda: admin_user
    app.dependency_overrides[get_db] = lambda: mock_db

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client

    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def member_client(member_user):
    mock_db = _make_mock_db()

    app.dependency_overrides[get_current_user] = lambda: member_user
    app.dependency_overrides[get_db] = lambda: mock_db

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client

    app.dependency_overrides.clear()


class _NoRealDatabaseSession:
    """Sustituto de `database.async_session` en los tests.

    La sesión global apunta a la base de `.env` (la de desarrollo). Un test que
    pase por código que la use sin sustituirla escribiría ahí: el middleware de
    uso guardaba `audit_logs` en cada petición. Aquí se entrega una sesión SIN
    conexión: crearla no falla (`get_db` la abre aunque la ruta conteste 401
    antes de consultar), pero cualquier consulta o commit con cambios lanza
    `UnboundExecutionError`. Los tests de integración la apuntan a la base de
    pruebas.
    """

    def __call__(self, *_args, **_kwargs):
        from sqlalchemy.ext.asyncio import AsyncSession

        return AsyncSession(expire_on_commit=False)


@pytest.fixture(autouse=True)
def _no_real_database_session(monkeypatch):
    from backend.db import database

    monkeypatch.setattr(database, "async_session", _NoRealDatabaseSession())


@pytest.fixture(autouse=True)
def _no_real_google_revoke(monkeypatch):
    """Desconectar Google revoca el token en Google: en los tests nunca sale a la red.

    Se sustituye donde lo usan las rutas; los tests de ``google_oauth.revoke_token``
    llaman a la función real con httpx simulado. Un test que quiera ver la
    llamada usa este fixture (``_no_real_google_revoke``) y mira sus llamadas.
    """
    from backend.api.routes import google_calendar, gsc

    fake = AsyncMock(return_value=True)
    monkeypatch.setattr(gsc, "revoke_token", fake)
    monkeypatch.setattr(google_calendar, "revoke_token", fake)
    return fake


@pytest.fixture(autouse=True)
def _no_real_gsc_monthly(monkeypatch):
    """El historial mensual de Search Console pide meses a Google tras importar
    el detalle: en los tests nunca sale a la red. Por defecto Google "no
    devuelve nada"; un test que quiera otra respuesta pasa `fetch_month=`."""
    from backend.services import gsc_detail_service

    fake = AsyncMock(return_value=[])
    monkeypatch.setattr(gsc_detail_service, "query_month", fake)
    return fake


@pytest.fixture(autouse=True)
def _no_real_ga4_leads(monkeypatch):
    """Los leads por landing se piden a GA4 detrás de los totales: en los tests
    nunca salen a la red. Por defecto GA4 "no devuelve nada"; un test que
    quiera otra respuesta pasa `fetch_leads=`."""
    from backend.services import ga4_leads

    fake = AsyncMock(return_value=[])
    monkeypatch.setattr(ga4_leads, "query_leads", fake)
    return fake


@pytest.fixture(autouse=True)
def _no_real_web_health_network(monkeypatch):
    """Dominio, certificado, robots.txt, sitemap y la revisión tras publicar
    nunca salen a la red en los tests: por defecto "no responde" (``timeout``) y
    no hay certificado. Un test que quiera otra respuesta pasa ``fetcher=`` /
    ``cert_reader=`` o vuelve a parchear estos nombres."""
    from backend.services.web import health, publish_check
    from backend.services.web.safe_http import FetchResult, TlsCertificate

    async def no_network(url, **_kwargs):
        return FetchResult(None, 0, url, error="timeout")

    async def no_cert(_host, **_kwargs):
        return TlsCertificate(error="timeout")

    monkeypatch.setattr(health, "fetch", no_network)
    monkeypatch.setattr(health, "fetch_tls_certificate", no_cert)
    monkeypatch.setattr(publish_check, "fetch", no_network)
