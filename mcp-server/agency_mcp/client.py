"""Cliente HTTP de la API de The Agency.

Entra con el usuario de la persona (como la extensión de Chrome) y manda el
JWT como Bearer, así que los permisos por módulo y el historial de Deshacer
funcionan igual que en la web. El token caduca a las 8 h: ante un 401 se
vuelve a entrar una sola vez y se repite la llamada.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from agency_mcp import __version__


class AgencyError(Exception):
    """Fallo de la API con un mensaje que se puede enseñar tal cual al modelo."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def _detail(response: httpx.Response) -> str:
    try:
        detail = response.json().get("detail")
    except (ValueError, AttributeError):
        detail = None
    if isinstance(detail, list):
        # Errores de validación de FastAPI: [{"loc": [...], "msg": "..."}]
        parts = []
        for item in detail:
            loc = ".".join(str(p) for p in item.get("loc", []) if p != "body")
            parts.append(f"{loc}: {item.get('msg')}" if loc else str(item.get("msg")))
        return "; ".join(parts)
    if isinstance(detail, dict) and detail.get("message"):
        # Conflictos con contexto: {"code": "...", "message": "...", "current": {...}}
        return str(detail["message"])
    if detail:
        return str(detail)
    return response.text[:300] or response.reason_phrase


class AgencyClient:
    def __init__(
        self,
        base_url: str,
        email: str,
        password: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 30.0,
    ):
        self.base_url = base_url.rstrip("/")
        self._email = email
        self._password = password
        self._token: str | None = None
        self._lock = asyncio.Lock()
        self._http = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=timeout,
            transport=transport,
            headers={"User-Agent": f"agency-mcp/{__version__}"},
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _login(self) -> None:
        try:
            response = await self._http.post(
                "/api/auth/login", json={"email": self._email, "password": self._password}
            )
        except httpx.HTTPError as exc:
            raise AgencyError(0, f"No se pudo conectar con {self.base_url}: {exc}") from exc
        # El login también deja cookies de sesión. Las tiramos: con cookie y sin
        # Bearer el backend exigiría CSRF, y aquí sólo queremos el Bearer.
        self._http.cookies.clear()
        if response.status_code != 200:
            raise AgencyError(
                response.status_code,
                f"No se pudo iniciar sesión en The Agency como {self._email}: {_detail(response)}",
            )
        self._token = response.json()["access_token"]

    async def _ensure_token(self) -> str:
        async with self._lock:
            if self._token is None:
                await self._login()
            assert self._token is not None
            return self._token

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
        timeout: float | None = None,
    ) -> Any:
        clean_params = {k: v for k, v in (params or {}).items() if v is not None}
        response: httpx.Response | None = None
        for attempt in range(2):
            token = await self._ensure_token()
            try:
                response = await self._http.request(
                    method,
                    path,
                    params=clean_params,
                    json=json,
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=timeout if timeout is not None else httpx.USE_CLIENT_DEFAULT,
                )
            except httpx.HTTPError as exc:
                raise AgencyError(0, f"No se pudo conectar con {self.base_url}: {exc}") from exc
            if response.status_code == 401 and attempt == 0:
                async with self._lock:
                    if self._token == token:
                        self._token = None
                continue
            break

        assert response is not None
        if response.status_code >= 400:
            raise AgencyError(response.status_code, f"{response.status_code}: {_detail(response)}")
        if response.status_code == 204 or not response.content:
            return None
        return response.json()

    async def get(self, path: str, **params: Any) -> Any:
        return await self.request("GET", path, params=params)

    async def post(self, path: str, json: Any = None, **kwargs: Any) -> Any:
        return await self.request("POST", path, json=json, **kwargs)

    async def put(self, path: str, json: Any = None, **kwargs: Any) -> Any:
        return await self.request("PUT", path, json=json, **kwargs)
