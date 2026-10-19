"""Unit rules for procedures in recurring tasks (no database)."""
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from backend.schemas.task import TaskCreate, TaskUpdate
from backend.services.domain_writes import UPDATABLE_TASK_FIELDS, _validate_procedure


def test_schema_trims_blank_and_rejects_non_http_links():
    body = TaskCreate(title="t", procedure_text="  \n ", procedure_url=" https://a.test/x ")
    assert body.procedure_text is None
    assert body.procedure_url == "https://a.test/x"
    for url in ("javascript:alert(1)", "ftp://a.test", "docs/proc"):
        with pytest.raises(ValidationError):
            TaskUpdate(procedure_url=url)
    assert TaskUpdate(procedure_url=None).procedure_url is None


def test_procedure_fields_are_patchable():
    assert {"procedure_text", "procedure_url"} <= UPDATABLE_TASK_FIELDS


def test_create_allows_template_and_generated_occurrence_only():
    _validate_procedure({"is_recurring": True, "procedure_text": "Pasos"})
    _validate_procedure({"recurring_parent_id": 7, "procedure_text": "Pasos"})
    _validate_procedure({"title": "Puntual", "procedure_text": None})
    with pytest.raises(HTTPException) as exc:
        _validate_procedure({"title": "Puntual", "procedure_url": "https://a.test"})
    assert exc.value.status_code == 422


def test_update_rejects_changes_outside_the_template():
    occurrence = SimpleNamespace(is_recurring=False, procedure_text="Pasos", procedure_url=None)
    _validate_procedure({"procedure_text": "Pasos", "procedure_url": None}, existing=occurrence)
    with pytest.raises(HTTPException):
        _validate_procedure({"procedure_text": "Otro"}, existing=occurrence)
    template = SimpleNamespace(is_recurring=True, procedure_text=None, procedure_url=None)
    _validate_procedure({"procedure_text": "Nuevo"}, existing=template)
    with pytest.raises(HTTPException):
        _validate_procedure({"is_recurring": False, "procedure_text": "Nuevo"}, existing=template)
