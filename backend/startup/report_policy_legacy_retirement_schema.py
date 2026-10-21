"""Retira ``client_report_policies.enabled`` / ``cadence`` (una sola cadencia).

Las sustituyeron ``weekly_enabled`` / ``monthly_enabled`` en
``report_policy_cadences_v1``, que ya rellenó cada política con la cadencia que
tenía. Ningún código las lee ni las escribe. Mecánica y perdón de P12:
``retirement_schema``.
"""
from backend.startup.retirement_schema import Retirement

STEP = Retirement("report_policy_legacy_retirement_v1.json")
CONTRACT = STEP.contract
RETIRED_TABLES = STEP.tables
RETIRED_COLUMNS = STEP.columns
apply = STEP.apply
verify = STEP.verify
MIGRATION = STEP.migration
