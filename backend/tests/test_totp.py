"""Códigos 2FA (TOTP) de Accesos: el cálculo y la lectura de la clave."""
import base64

import pytest

from backend.services import totp

# Vectores del RFC 6238 (apéndice B): clave ASCII "1234567890…" según el algoritmo.
SHA1 = base64.b32encode(b"12345678901234567890").decode()
SHA256 = base64.b32encode(b"12345678901234567890123456789012").decode()
SHA512 = base64.b32encode(b"1234567890" * 6 + b"1234").decode()


@pytest.mark.parametrize("timestamp, sha1, sha256, sha512", [
    (59, "94287082", "46119246", "90693936"),
    (1111111109, "07081804", "68084774", "25091201"),
    (1234567890, "89005924", "91819424", "93441116"),
    (20000000000, "65353130", "77737706", "47863826"),
])
def test_vectores_del_rfc_6238(timestamp, sha1, sha256, sha512):
    for secret, algorithm, expected in ((SHA1, "SHA1", sha1), (SHA256, "SHA256", sha256), (SHA512, "SHA512", sha512)):
        config = totp.TotpConfig(secret=secret.rstrip("="), digits=8, algorithm=algorithm)
        assert totp.code_at(config, timestamp) == expected


def test_clave_suelta_con_espacios_y_minusculas():
    config = totp.parse("jbsw y3dp ehpk 3pxp")
    assert config == totp.TotpConfig(secret="JBSWY3DPEHPK3PXP")
    assert totp.code_at(config, 59) == totp.code_at(totp.parse("JBSWY3DPEHPK3PXP"), 59)


def test_enlace_otpauth_con_parametros():
    config = totp.parse("otpauth://totp/Google:yo%40magnify.ing?secret=JBSWY3DPEHPK3PXP&issuer=Google"
                        "&algorithm=sha256&digits=8&period=60")
    assert (config.algorithm, config.digits, config.period) == ("SHA256", 8, 60)
    assert totp.parse(totp.to_uri(config)) == config


@pytest.mark.parametrize("raw, fragment", [
    ("123456", "no el código de 6 dígitos"),
    ("", "vacía"),
    ("otpauth://hotp/x?secret=JBSWY3DPEHPK3PXP&counter=1", "hotp"),
    ("otpauth://totp/x?issuer=Google", "no trae la clave"),
    ("otpauth://totp/x?secret=JBSWY3DPEHPK3PXP&algorithm=MD5", "algoritmo"),
    ("otpauth://totp/x?secret=JBSWY3DPEHPK3PXP&digits=4", "6, 7 u 8"),
    ("otpauth://totp/x?secret=JBSWY3DPEHPK3PXP&period=5", "segundos"),
    ("otpauth://totp/x?secret=JBSWY3DPEHPK3PXP&digits=seis", "no es un número"),
])
def test_claves_que_no_sirven_dicen_por_que(raw, fragment):
    with pytest.raises(totp.TotpError, match=fragment):
        totp.parse(raw)


def test_el_codigo_de_ahora_el_siguiente_y_lo_que_le_queda():
    config = totp.TotpConfig(secret="JBSWY3DPEHPK3PXP")
    out = totp.current(config, now=1_000_000_010)
    assert out["remaining"] == 10 and out["period"] == 30 and out["digits"] == 6
    assert out["code"] == totp.code_at(config, 1_000_000_010)
    assert out["next_code"] == totp.code_at(config, 1_000_000_040)
    assert len(out["code"]) == 6 and out["code"].isdigit()
