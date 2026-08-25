"""Regression tests for daily updates endpoints.

Covers:
- List dailys → 200
- GET nonexistent daily → 404
- Invalid date filter → 400
- Prefill endpoint
- DELETE nonexistent → 404
- _to_response with null/malformed data
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock
from datetime import datetime, timezone

from backend.db.models import DailyUpdateStatus

_NOW = datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc)


@pytest.mark.asyncio
class TestDailysList:
    """GET /api/dailys"""

    async def test_list_dailys_returns_200(self, admin_client):
        resp = await admin_client.get("/api/dailys")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    async def test_list_with_date_filter(self, admin_client):
        resp = await admin_client.get(
            "/api/dailys",
            params={"date_from": "2025-01-01", "date_to": "2025-12-31"},
        )
        assert resp.status_code == 200

    async def test_invalid_date_format(self, admin_client):
        resp = await admin_client.get(
            "/api/dailys", params={"date_from": "not-a-date"}
        )
        assert resp.status_code == 400


@pytest.mark.asyncio
class TestDailysGet:
    """GET /api/dailys/{id}"""

    async def test_get_nonexistent_daily(self, admin_client):
        resp = await admin_client.get("/api/dailys/9999")
        assert resp.status_code == 404


@pytest.mark.asyncio
class TestDailysPrefill:
    """GET /api/dailys/prefill"""

    async def test_prefill_returns_text(self, admin_client):
        resp = await admin_client.get("/api/dailys/prefill")
        assert resp.status_code == 200
        data = resp.json()
        assert "text" in data
        assert "completed_count" in data
        assert "worked_on_count" in data


@pytest.mark.asyncio
class TestDailysDelete:
    """DELETE /api/dailys/{id}"""

    async def test_delete_nonexistent_daily(self, admin_client):
        resp = await admin_client.delete("/api/dailys/9999")
        assert resp.status_code == 404


class TestDailysToResponse:
    """Test _to_response handles various data shapes."""

    def test_with_valid_parsed_data(self):
        from backend.api.routes.dailys import _to_response

        mock_daily = MagicMock()
        mock_daily.id = 1
        mock_daily.user_id = 1
        mock_daily.user = MagicMock(full_name="David")
        mock_daily.date = "2025-06-01"
        mock_daily.raw_text = "Worked on stuff"
        mock_daily.parsed_data = {
            "tasks": [
                {"client": "Acme", "description": "SEO audit", "hours": 2.0}
            ],
            "blockers": [],
            "summary": "Good day",
        }
        mock_daily.status = DailyUpdateStatus.draft
        mock_daily.discord_sent_at = None
        mock_daily.created_at = _NOW
        mock_daily.updated_at = _NOW

        result = _to_response(mock_daily)
        assert result.user_name == "David"
        assert result.status == DailyUpdateStatus.draft

    def test_with_null_user(self):
        from backend.api.routes.dailys import _to_response

        mock_daily = MagicMock()
        mock_daily.id = 2
        mock_daily.user_id = 1
        mock_daily.user = None
        mock_daily.date = "2025-06-01"
        mock_daily.raw_text = "Test"
        mock_daily.parsed_data = None
        mock_daily.status = DailyUpdateStatus.draft
        mock_daily.discord_sent_at = None
        mock_daily.created_at = _NOW
        mock_daily.updated_at = _NOW

        result = _to_response(mock_daily)
        assert result.user_name is None
        assert result.parsed_data is None

    def test_with_malformed_parsed_data(self):
        from backend.api.routes.dailys import _to_response

        mock_daily = MagicMock()
        mock_daily.id = 3
        mock_daily.user_id = 1
        mock_daily.user = MagicMock(full_name="Test")
        mock_daily.date = "2025-06-01"
        mock_daily.raw_text = "Test"
        mock_daily.parsed_data = {"invalid": "structure"}
        mock_daily.status = DailyUpdateStatus.draft
        mock_daily.discord_sent_at = None
        mock_daily.created_at = _NOW
        mock_daily.updated_at = _NOW

        # Should not crash — returns None for parsed_data if schema doesn't match
        result = _to_response(mock_daily)
        assert result is not None


@pytest.mark.asyncio
class TestDailyParserBudget:
    """El presupuesto de tiempo del parseo tiene que caber el daily real.

    25 ago 2026: Nacho no podía enviar el recap del día. El daily se guardaba
    ("Sin parsear") y el botón de Discord contestaba "El daily no tiene datos
    parseados". La causa era este presupuesto: `with_options(timeout=12)` se
    había puesto por debajo de lo que tarda la propia generación.

    Medido contra la API real (claude-sonnet-4-6, max_tokens=4096):

        3 proyectos / 1,4k chars ->  7,3 s
        5 proyectos / 2,3k chars ->  9,3 s
        8 proyectos / 3,6k chars -> 12,6 s   <- se cortaba
       12 proyectos / 5,3k chars -> 20,1 s

    El test guarda las dos mitades del invariante: suficiente para el peor caso
    medido, y sin desbordar el timeout que el frontend le da a la petición.
    """

    # Lo que `dailysApi.submit/reparse/edit` conceden en frontend/src/lib/api.ts
    PRESUPUESTO_CLIENTE_S = 90.0
    # Peor caso medido (20,1 s) con margen: un daily aún más largo debe caber.
    PEOR_CASO_MEDIDO_S = 25.0

    async def test_el_parseo_cabe_en_el_daily_mas_largo_y_en_el_timeout_del_cliente(
        self, monkeypatch
    ):
        from backend.services import daily_parser

        opciones: dict = {}

        class _FakeMessages:
            async def create(self, **_kwargs):
                msg = MagicMock()
                msg.stop_reason = "end_turn"
                bloque = MagicMock()
                bloque.type = "text"
                bloque.text = '{"projects": [], "general": [], "tomorrow": []}'
                msg.content = [bloque]
                return msg

        class _FakeClient:
            messages = _FakeMessages()

            def with_options(self, **kwargs):
                opciones.update(kwargs)
                return self

        monkeypatch.setattr(daily_parser, "get_anthropic_client", lambda: _FakeClient())

        await daily_parser.parse_daily_update("Cliente Acme:\n- Auditoría técnica")

        timeout = opciones["timeout"]
        intentos = opciones["max_retries"] + 1

        assert timeout >= self.PEOR_CASO_MEDIDO_S, (
            f"timeout={timeout}s se queda por debajo del daily más largo medido "
            f"({self.PEOR_CASO_MEDIDO_S}s): el recap de final de día se cortaría "
            f"a media generación y quedaría sin parsear."
        )
        assert timeout * intentos <= self.PRESUPUESTO_CLIENTE_S, (
            f"{timeout}s x {intentos} intentos = {timeout * intentos}s desborda "
            f"los {self.PRESUPUESTO_CLIENTE_S}s de axios: el navegador cortaría "
            f"antes de que el servidor terminase."
        )


class TestEmbedDailySinEstructurar:
    """Un fallo de la IA no puede dejar al autor sin poder publicar su informe.

    Antes, `POST /dailys/{id}/send-discord` devolvía 400 "El daily no tiene datos
    parseados" cuando el parseo había fallado. El daily estaba guardado y era
    perfectamente legible, pero no había forma de mandarlo. Ahora se publica el
    texto en crudo.
    """

    def test_el_embed_en_crudo_conserva_el_texto_del_autor(self):
        from backend.services.daily_parser import format_raw_daily_embed

        raw = "Acme:\n- Auditoría técnica\n- Llamada con el cliente"
        embed = format_raw_daily_embed(raw, "Nacho", "2026-08-25")

        assert embed["title"] == "Nacho — 2026-08-25"
        assert embed["description"] == raw
        # Que se ve a simple vista que este daily no pasó por la IA.
        assert "Sin estructurar" in embed["footer"]["text"]

    def test_el_embed_en_crudo_respeta_el_limite_de_discord(self):
        from backend.services.daily_parser import format_raw_daily_embed

        embed = format_raw_daily_embed("x" * 9000, "Nacho", "2026-08-25")

        # Discord rechaza la petición entera si `description` pasa de 4096.
        assert len(embed["description"]) <= 4096
        assert embed["description"].endswith("(recortado)")
