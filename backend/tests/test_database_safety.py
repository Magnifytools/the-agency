import pytest

from backend.tests.database_safety import validate_test_database_url


@pytest.mark.parametrize("url", [
    "postgresql+asyncpg://agency:pw@localhost/the_agency_test",
    "postgresql+asyncpg://david@localhost/agency_phase1_verify_20260917",
    "postgresql://agency:pw@postgres:5432/agency_test_ci",
])
def test_accepts_isolated_databases(url):
    validate_test_database_url(url, "postgresql://agency:pw@localhost/the_agency")


@pytest.mark.parametrize("url,application", [
    ("postgresql://agency@remote.railway.app/agency_test", "postgresql://agency@localhost/app"),
    ("postgresql://agency@localhost/the_agency", "postgresql://agency@remote/app"),
    ("postgresql://agency:new@127.0.0.1/agency_test", "postgresql+asyncpg://agency:old@localhost/agency_test"),
    ("postgresql://agency@localhost/latest", "postgresql://agency@remote/app"),
])
def test_rejects_unsafe_databases_without_connecting(url, application):
    with pytest.raises(ValueError):
        validate_test_database_url(url, application)
