import json

import pytest

from backend.services import daily_parser


class _Messages:
    def __init__(self, payload):
        self.payload = payload
        self.request = None

    async def create(self, **kwargs):
        self.request = kwargs
        return type(
            "Response",
            (),
            {
                "content": [
                    type(
                        "Block",
                        (),
                        {"type": "text", "text": json.dumps(self.payload)},
                    )()
                ]
            },
        )()


class _Client:
    def __init__(self, payload):
        self.messages = _Messages(payload)

    def with_options(self, **_kwargs):
        return self


@pytest.mark.asyncio
async def test_parser_separates_facts_and_preserves_valid_keys(monkeypatch):
    payload = {
        "projects": [
            {
                "name": "Acme",
                "client": "Acme",
                "tasks": [
                    {
                        "description": "Auditoría",
                        "details": "",
                        "fact_keys": ["time_logged:4"],
                    }
                ],
            }
        ],
        "general": [{"description": "Nota libre", "details": "", "fact_keys": []}],
        "tomorrow": [],
    }
    client = _Client(payload)
    monkeypatch.setattr(daily_parser, "get_anthropic_client", lambda: client)
    result = await daily_parser.parse_daily_update(
        "Mi nota",
        source_facts=[
            {
                "key": "time_logged:4",
                "kind": "time_logged",
                "minutes": 30,
                "client_id": 7,
                "client_name": "Cliente canónico",
                "project_id": 8,
                "project_name": "Proyecto canónico",
            }
        ],
    )
    prompt = client.messages.request["messages"][0]["content"]
    assert (
        "<source_facts>" in prompt and "<user_notes>\nMi nota\n</user_notes>" in prompt
    )
    assert result["projects"][0]["name"] == "Proyecto canónico"
    assert result["projects"][0]["client"] == "Cliente canónico"
    assert result["projects"][0]["tasks"][0]["fact_keys"] == ["time_logged:4"]
    assert result["general"][0]["fact_keys"] == []


@pytest.mark.asyncio
async def test_parser_rejects_model_claim_of_unknown_fact(monkeypatch):
    client = _Client(
        {
            "projects": [],
            "general": [
                {
                    "description": "Inventado",
                    "details": "",
                    "fact_keys": ["task_completed:999:x"],
                }
            ],
            "tomorrow": [],
        }
    )
    monkeypatch.setattr(daily_parser, "get_anthropic_client", lambda: client)
    with pytest.raises(ValueError, match="unknown source fact"):
        await daily_parser.parse_daily_update("Texto", source_facts=[])


@pytest.mark.asyncio
async def test_parser_rejects_cross_project_facts_with_duplicate_titles(monkeypatch):
    client = _Client(
        {
            "projects": [
                {
                    "name": "Proyecto inventado",
                    "client": "Cliente inventado",
                    "tasks": [
                        {
                            "description": "Mismo título",
                            "details": "",
                            "fact_keys": ["time_logged:1", "time_logged:2"],
                        }
                    ],
                }
            ],
            "general": [],
            "tomorrow": [],
        }
    )
    monkeypatch.setattr(daily_parser, "get_anthropic_client", lambda: client)
    facts = [
        {
            "key": "time_logged:1",
            "title": "Mismo título",
            "project_id": 10,
            "project_name": "Proyecto A",
        },
        {
            "key": "time_logged:2",
            "title": "Mismo título",
            "project_id": 11,
            "project_name": "Proyecto B",
        },
    ]
    with pytest.raises(ValueError, match="different projects"):
        await daily_parser.parse_daily_update("Texto", source_facts=facts)


def test_discord_markers_do_not_claim_waiting_or_planned_work_as_completed():
    parsed = {
        "projects": [
            {
                "name": "Proyecto",
                "client": "Cliente",
                "tasks": [
                    {
                        "description": "Espero respuesta",
                        "details": "",
                        "fact_keys": ["task_waiting:1:open"],
                    },
                    {
                        "description": "Lo haré mañana",
                        "details": "",
                        "fact_keys": ["next_step:2:2026-09-22"],
                    },
                    {
                        "description": "Mezcla de fuentes",
                        "details": "",
                        "fact_keys": ["time_logged:3", "task_completed:3:x"],
                    },
                ],
            }
        ],
        "general": [{"description": "Nota libre", "details": "", "fact_keys": []}],
        "tomorrow": [],
    }
    source_facts = [
        {"key": "task_waiting:1:open", "kind": "task_waiting"},
        {"key": "next_step:2:2026-09-22", "kind": "next_step"},
        {"key": "time_logged:3", "kind": "time_logged"},
        {"key": "task_completed:3:x", "kind": "task_completed"},
    ]

    formatted = daily_parser.format_daily_for_discord(
        parsed, "Ana", "2026-09-21", source_facts=source_facts
    )

    assert "⏸ Espero respuesta" in formatted
    assert "➡️ Lo haré mañana" in formatted
    assert "• Mezcla de fuentes" in formatted
    assert "• Nota libre" in formatted
    assert "✅ Espero respuesta" not in formatted
