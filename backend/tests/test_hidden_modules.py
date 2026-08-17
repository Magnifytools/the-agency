"""Los módulos ocultos: una sola lista, y que no se desincronice.

La reducción de ago 2026 apaga 20 módulos (router no registrado + pantalla
oculta). Ese estado se escribe en DOS ficheros —``backend/core/modules.py`` y
``frontend/src/lib/hidden-modules.ts``— porque no comparten runtime.

Dos listas es exactamente la forma en que este repositorio se ha equivocado ya
dos veces: los cuatro mapas de estado de rentabilidad, y los defaults de poda de
Vigil. Aquí el test lee el fichero de TypeScript y compara.

Si reactivas un módulo, quítalo de los dos sitios o este test te lo dirá.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import pytest

from backend.core.modules import HIDDEN_MODULES, hidden_modules, is_enabled, is_hidden

TS_FILE = (
    Path(__file__).resolve().parents[2]
    / "frontend"
    / "src"
    / "lib"
    / "hidden-modules.ts"
)


def _modulos_del_frontend() -> set[str]:
    """Extrae las claves del array HIDDEN_MODULES del fichero TypeScript."""
    src = TS_FILE.read_text(encoding="utf-8")
    bloque = re.search(
        r"export const HIDDEN_MODULES = \[(.*?)\] as const", src, re.DOTALL
    )
    assert bloque, "No se encontró el array HIDDEN_MODULES en hidden-modules.ts"
    return set(re.findall(r'"([a-z_]+)"', bloque.group(1)))


class TestListasSincronizadas:
    def test_el_fichero_del_frontend_existe(self):
        assert TS_FILE.is_file(), f"falta {TS_FILE}"

    def test_backend_y_frontend_ocultan_lo_mismo(self):
        front = _modulos_del_frontend()
        back = set(HIDDEN_MODULES)
        assert front == back, (
            "Las listas de módulos ocultos divergen.\n"
            f"  Solo en el backend:  {sorted(back - front)}\n"
            f"  Solo en el frontend: {sorted(front - back)}\n"
            "Actualiza backend/core/modules.py Y frontend/src/lib/hidden-modules.ts."
        )

    def test_las_rutas_ocultas_apuntan_a_modulos_conocidos(self):
        """HIDDEN_ROUTES no puede referirse a un módulo que no existe."""
        src = TS_FILE.read_text(encoding="utf-8")
        bloque = re.search(
            r"export const HIDDEN_ROUTES[^=]*= \{(.*?)\n\}", src, re.DOTALL
        )
        assert bloque, "No se encontró HIDDEN_ROUTES"
        referidos = set(re.findall(r':\s*"([a-z_]+)"', bloque.group(1)))
        desconocidos = referidos - _modulos_del_frontend()
        assert not desconocidos, f"HIDDEN_ROUTES apunta a módulos inexistentes: {desconocidos}"


class TestRoutersRegistrados:
    """Lo que importa de verdad: qué responde y qué no, EN PRODUCCIÓN.

    La suite corre con ``AGENCY_HIDDEN_MODULES=""`` (ver conftest.py) para que el
    código oculto siga probado. Así que la app del proceso de test tiene TODOS los
    routers y no sirve para comprobar el ocultamiento.

    Por eso esto levanta la aplicación en un **subproceso limpio**, sin esa
    variable, y lee las rutas que quedan registradas: exactamente lo que hará
    Railway al arrancar.
    """

    @pytest.fixture(scope="class")
    def rutas(self):
        import json
        import subprocess

        raiz = Path(__file__).resolve().parents[2]
        entorno = {k: v for k, v in os.environ.items() if k != "AGENCY_HIDDEN_MODULES"}
        entorno["PYTHONPATH"] = str(raiz)

        proc = subprocess.run(
            [
                sys.executable,
                "-c",
                "import json;from backend.main import app;"
                "print(json.dumps(sorted({r.path for r in app.router.routes "
                "if getattr(r,'path','').startswith('/api')})))",
            ],
            capture_output=True,
            text=True,
            env=entorno,
            cwd=str(raiz),
            timeout=120,
        )
        assert proc.returncode == 0, (
            f"la app no arranca con la configuración de producción:\n{proc.stderr[-2000:]}"
        )
        return set(json.loads(proc.stdout.strip().splitlines()[-1]))

    @pytest.mark.parametrize(
        "prefijo",
        [
            "/api/reports", "/api/cfo", "/api/vault", "/api/automations",
            "/api/leads", "/api/growth", "/api/proposals",
            "/api/holded", "/api/income", "/api/expenses", "/api/taxes",
            "/api/forecasts", "/api/billing", "/api/communications",
            "/api/invitations", "/api/investments",
            "/api/service-templates", "/api/advisor", "/api/balance",
        ],
    )
    def test_los_ocultos_no_estan_registrados(self, rutas, prefijo):
        encontradas = [r for r in rutas if r.startswith(prefijo)]
        assert not encontradas, f"{prefijo} debería estar oculto y responde: {encontradas}"

    @pytest.mark.parametrize(
        "ruta",
        [
            "/api/auth/me", "/api/clients", "/api/projects", "/api/tasks",
            "/api/time-entries", "/api/dashboard/overview", "/api/digests",
            "/api/dailys", "/api/inbox", "/api/users", "/api/notifications",
            # search: 0 llamadas pero es la paleta ⌘K del shell, se queda
            "/api/search",
            # pm: el panel "Asistente PM" vive dentro del dashboard
            "/api/pm/insights",
            # discord: la PANTALLA está oculta, pero el dashboard lee esto para
            # ofrecer "Enviar a Discord" en el Resumen Diario — y ese envío se usa
            "/api/discord/settings",
            "/api/dailys/{daily_id}/send-discord",
            # my-week: la PANTALLA está oculta, pero este router sirve los
            # festivos de empresa que se gestionan desde Ajustes, y Ajustes se
            # conserva
            "/api/my-week/holidays",
        ],
    )
    def test_el_nucleo_sigue_registrado(self, rutas, ruta):
        assert ruta in rutas, f"{ruta} es del núcleo y ha desaparecido"

    def test_la_extension_de_chrome_sigue_funcionando(self, rutas):
        """La extensión es el cliente de Nacho: si algo suyo cae, se entera él."""
        for r in [
            "/api/auth/me", "/api/calendar/upcoming", "/api/clients",
            "/api/inbox", "/api/inbox/count", "/api/projects", "/api/tasks",
            "/api/time-entries", "/api/timer/active", "/api/timer/pause",
            "/api/timer/resume", "/api/timer/start", "/api/timer/stop",
        ]:
            assert r in rutas, f"la extensión llama a {r} y ya no está registrada"


class TestOverridePorEntorno:
    """Reactivar en Railway sin desplegar."""

    def test_sin_variable_manda_la_lista_del_codigo(self, monkeypatch):
        monkeypatch.delenv("AGENCY_HIDDEN_MODULES", raising=False)
        assert hidden_modules() == HIDDEN_MODULES

    def test_la_variable_sustituye_la_lista(self, monkeypatch):
        monkeypatch.setenv("AGENCY_HIDDEN_MODULES", "reports, cfo")
        assert hidden_modules() == {"reports", "cfo"}
        assert is_hidden("reports")
        assert is_enabled("finance"), "finance no estaba en la variable: debe volver"

    def test_variable_vacia_reactiva_todo(self, monkeypatch):
        """Cadena vacía es una respuesta, no 'sin configurar'."""
        monkeypatch.setenv("AGENCY_HIDDEN_MODULES", "")
        assert hidden_modules() == frozenset()
        assert is_enabled("finance") and is_enabled("reports")

    def test_tolera_espacios_y_comas_sueltas(self, monkeypatch):
        monkeypatch.setenv("AGENCY_HIDDEN_MODULES", " reports , , cfo ,")
        assert hidden_modules() == {"reports", "cfo"}


def test_search_y_pm_no_estan_ocultos():
    """Excepciones deliberadas, documentadas en core/modules.py.

    Ambos tienen cifras que invitarían a ocultarlos, pero no son pantallas: son
    piezas dentro de páginas que sí se conservan (la paleta ⌘K y el panel del
    dashboard). Este test existe para que la excepción sea explícita y no se
    pierda en una limpieza futura.
    """
    assert "search" not in HIDDEN_MODULES
    assert "pm" not in HIDDEN_MODULES
