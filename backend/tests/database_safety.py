"""Reject destructive integration tests unless the database is isolated/local."""
import re
from urllib.parse import unquote, urlsplit


def validate_test_database_url(test_url: str, application_url: str) -> None:
    def identity(url):
        parsed = urlsplit(url)
        return parsed.hostname, parsed.port or 5432, unquote(parsed.path.lstrip("/"))

    host, port, name = identity(test_url)
    app_host, app_port, app_name = identity(application_url)
    local_hosts = {"localhost", "127.0.0.1", "::1"}
    same_host = host == app_host or (host in local_hosts and app_host in local_hosts)
    if same_host and port == app_port and name == app_name:
        raise ValueError("Integration tests cannot use the application database")
    if host not in local_hosts | {"postgres"}:
        raise ValueError("Integration tests require an isolated local PostgreSQL host")
    if not re.search(r"(?:^|_)(?:test|tests|phase1)(?:_|$)", name):
        raise ValueError("Integration database name must explicitly identify a test database")
