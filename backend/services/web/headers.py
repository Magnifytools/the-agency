"""Cabeceras HTTP para pedir las webs de los clientes (portado de Vigil).

Por qué esto es un módulo y no una constante suelta
---------------------------------------------------
El User-Agent es la parte más frágil de mirar webs ajenas y falla en silencio:
si un WAF empieza a devolver 403 a nuestra petición, no es que la web se haya
caído, es que nos bloquean. Por eso un 401/403/429 o un desafío de Cloudflare
cuentan como "bloqueo", nunca como caída (ver ``uptime.classify``).

Medido por Vigil contra fitgeneration.es (Cloudflare) el 22-jul-2026:

    UA Chrome/131.0.0.0 (macOS)  → 403  (reproducible, 3/3)
    UA Chrome/126.0.0.0 (macOS)  → 200

No bloquea "lo que parece un bot", bloquea una cadena de UA concreta. De ahí:

  1. El UA se fija aquí y es CONFIGURABLE por cliente
     (``client_web_settings.user_agent``). Nunca hardcodearlo en el fetcher.
  2. Subir la versión de Chrome de este fichero NO es cosmético: puede hacer
     que la web de un cliente entero salga como bloqueada. Verificar antes.
"""
from __future__ import annotations

# Verificado 200 contra fitgeneration.es (Cloudflare) el 22-jul-2026 (Vigil).
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


def browser_headers(user_agent: str | None = None) -> dict[str, str]:
    """Set de cabeceras coherente de navegador.

    Un UA suelto sin ``Accept``/``Accept-Language`` es una huella de bot evidente
    para muchos WAF. Se manda el trío completo siempre.
    """
    ua = user_agent.strip() if isinstance(user_agent, str) and user_agent.strip() else DEFAULT_USER_AGENT
    return {
        "User-Agent": ua,
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;q=0.9,"
            "image/avif,image/webp,*/*;q=0.8"
        ),
        "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
    }
