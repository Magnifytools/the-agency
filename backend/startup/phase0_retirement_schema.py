"""Fase 0 de Agency 2.0: retira las tablas y columnas de los módulos borrados.

Borra las tablas de invitations, vault, resources, evidence, reports,
automations y my_week, y las columnas decorativas del cliente y
``users.invited_by``. Mecánica y perdón de P12: ``retirement_schema``.
"""
from backend.startup.retirement_schema import Retirement

STEP = Retirement("phase0_retirement_v1.json")
CONTRACT = STEP.contract
RETIRED_TABLES = STEP.tables
RETIRED_COLUMNS = STEP.columns
apply = STEP.apply
verify = STEP.verify
MIGRATION = STEP.migration
