"""Retira ``alert_settings.notify_in_app`` / ``notify_email``.

Se guardaban y devolvían en ``/api/pm/settings/alerts``, pero ningún aviso las
consultaba y no tenían pantalla (regla "No datos decorativos"). Los avisos de
escritorio de la extensión guardan su preferencia en el navegador. Mecánica y
perdón de P12: ``retirement_schema``.
"""
from backend.startup.retirement_schema import Retirement

STEP = Retirement("alert_settings_notify_retirement_v1.json")
CONTRACT = STEP.contract
RETIRED_TABLES = STEP.tables
RETIRED_COLUMNS = STEP.columns
apply = STEP.apply
verify = STEP.verify
MIGRATION = STEP.migration
