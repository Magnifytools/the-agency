"""Retira lo que añadió ``vigil_v1``: la tabla ``vigil_summary`` y ``clients.vigil_slug``
(con ``uq_clients_vigil_slug``, que cae con la columna).

Vigil se apagó el 23 oct 2026 y la fase 3b ya sacó del código el job, el
servicio y el ORM: nada las lee. Mecánica: ``retirement_schema``. Como
``vigil_v1`` no es de P12, su ``verify`` mira si este paso ya está aplicado
(``RETIREMENT_VERSION``) y entonces acepta que no estén.
"""
from backend.startup.retirement_schema import Retirement

STEP = Retirement("vigil_retirement_v1.json")
CONTRACT = STEP.contract
RETIRED_TABLES = STEP.tables
RETIRED_COLUMNS = STEP.columns
apply = STEP.apply
verify = STEP.verify
MIGRATION = STEP.migration
