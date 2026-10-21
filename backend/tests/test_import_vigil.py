"""Piezas puras de ``scripts/import_vigil.py`` (sin base de datos).

Lo de verdad (importar, repetir, abortar, re-cifrar) está en
``tests/integration/test_import_vigil.py`` contra Postgres real.
"""
from __future__ import annotations

import base64
import hashlib
import json
import uuid
from datetime import UTC, datetime

import pytest
from cryptography.fernet import Fernet, InvalidToken

from backend.scripts import import_vigil as iv
from backend.services.web import capture_defaults as defaults


def test_ids_de_vigil_se_conservan_y_los_raros_se_derivan_estables():
    real = str(uuid.uuid4())
    assert iv.as_uuid("watches", real) == uuid.UUID(real)
    derived = iv.as_uuid("watches", "42")
    assert derived == uuid.uuid5(iv.VIGIL_NAMESPACE, "watches:42") == iv.as_uuid("watches", "42")
    assert derived != iv.as_uuid("changes", "42")  # la tabla entra en el id
    assert iv.as_uuid("watches", None) is None and iv.as_uuid("watches", "") is None


def test_fechas_de_vigil():
    assert iv.as_dt("2026-07-22T04:30:00Z") == datetime(2026, 7, 22, 4, 30, tzinfo=UTC)
    assert iv.as_dt("2026-07-22T04:30:00") == datetime(2026, 7, 22, 4, 30, tzinfo=UTC)
    assert iv.as_dt(None) is None
    assert iv.as_date("2026-07-22").isoformat() == "2026-07-22"


def test_lo_que_era_el_default_de_vigil_queda_null():
    vigil_defaults = {
        "digest_min_severity": "info",
        "default_ignore_selectors": json.dumps(list(defaults.DEFAULT_IGNORE_SELECTORS)),
        "default_ignore_regexes": json.dumps(list(defaults.DEFAULT_IGNORE_REGEXES)),
        "max_concurrency": 6, "request_timeout_s": 20, "crawl_delay_ms": 300,
        "sweep_weekdays": "[1,2,3,4,5]", "sweep_skip_dates": "[]", "sweep_summary_to_slack": 1,
        "user_agent": None, "default_content_selector": None,
    }
    assert all(v is None for v in iv.settings_values(vigil_defaults, [], "x").values())
    # El default viejo (pre-003, con [aria-live]) también es "default".
    old = {**vigil_defaults, "default_ignore_selectors": json.dumps(iv._OLD_DEFAULT_SELECTORS)}
    assert iv.settings_values(old, [], "x")["default_ignore_selectors"] is None

    custom = iv.settings_values({**vigil_defaults, "default_ignore_selectors": '[".promo"]', "crawl_delay_ms": 0,
                                 "sweep_weekdays": "[1,2,3,4,5,6]", "sweep_summary_to_slack": 0,
                                 "digest_min_severity": "warning"}, [], "x")
    assert custom["default_ignore_selectors"] == [".promo"] and custom["crawl_delay_ms"] == 0
    assert custom["sweep_weekdays"] == [1, 2, 3, 4, 5, 6] and custom["sweep_summary_to_slack"] is False
    assert custom["digest_min_severity"] == "warning"


def test_json_roto_no_rompe_la_importacion():
    warnings: list[str] = []
    assert iv.as_json("{no es json", warnings, "watch_state x") is None
    assert warnings and "watch_state x" in warnings[0]


def test_webhook_con_el_esquema_de_vigil():
    key = "clave-vigil"
    vigil = Fernet(base64.urlsafe_b64encode(hashlib.sha256(key.encode()).digest()))
    hook = "https://hooks.slack.com/services/T/B/x"
    ciphertext = "v1:" + vigil.encrypt(hook.encode()).decode()
    assert iv.decrypt_vigil_webhook(ciphertext, iv.vigil_fernet(key)) == hook
    with pytest.raises(InvalidToken):
        iv.decrypt_vigil_webhook(ciphertext, iv.vigil_fernet("otra"))
    with pytest.raises(ValueError):
        iv.decrypt_vigil_webhook(hook, iv.vigil_fernet(key))


def test_la_clave_se_lee_del_entorno_o_se_pide_sin_eco(monkeypatch):
    monkeypatch.setenv("VIGIL_SECRET_KEY", "de-entorno")
    monkeypatch.setattr(iv.getpass, "getpass", lambda *_a: pytest.fail("no debía preguntar"))
    assert iv.prompt_vigil_key() == "de-entorno"
    monkeypatch.delenv("VIGIL_SECRET_KEY")
    monkeypatch.setattr(iv.getpass, "getpass", lambda *_a: "tecleada")
    assert iv.prompt_vigil_key() == "tecleada"
    monkeypatch.setattr(iv.getpass, "getpass", lambda *_a: "")
    with pytest.raises(iv.ImportAborted):
        iv.prompt_vigil_key()


def test_map_mal_escrito():
    assert iv.parse_map(["fit=12", " demo = 3 "]) == {"fit": 12, "demo": 3}
    for bad in (["fit"], ["fit=doce"], ["=3"]):
        with pytest.raises(iv.ImportAborted):
            iv.parse_map(bad)
