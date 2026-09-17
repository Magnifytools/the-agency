# Python dependency maintenance

The backend targets Python 3.12. Install `backend/requirements.txt` as one set: the framework/parser and pytest/plugin versions must be resolved together.

| Component | Version |
|---|---|
| FastAPI / Starlette | 0.135.1 / 1.3.1 |
| python-multipart | 0.0.31 |
| PyJWT | 2.14.0 |
| cryptography | 50.0.1 |
| pyasn1 / pyasn1-modules | 0.6.4 / 0.4.2 |
| pytest / pytest-asyncio | 9.0.3 / 1.3.0 |
| pip bootstrap in Docker and CI | 26.2.1 |

JWT signing and decoding use PyJWT. The server still chooses the allowed algorithm, requires expiration, and keeps the existing `sub`, `exp`, and `jti` wire format. Existing HS256 tokens remain valid until their original expiration or revocation; this migration does not rotate keys or invalidate sessions. Cookie/CSRF and Bearer authentication continue to use the same endpoints. Fernet encryption and its existing key derivation remain unchanged; cryptography is now an explicit dependency rather than an incidental JWT extra.

The clean dependency graph no longer contains python-jose, ecdsa, or rsa. ASN.1 remains needed by the Google authentication dependencies and is constrained to the patched version.

## Verification

Use a disposable local PostgreSQL test database, distinct from the application database. The test harness validates that target before connecting and resets its schema. Do not point it at an application database.

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install --upgrade pip==26.2.1
.venv/bin/python -m pip install -r backend/requirements.txt pip-audit==2.10.1
.venv/bin/python -m pip check
: "${TEST_DATABASE_URL:?Set an isolated local test database}"
REQUIRE_TEST_DATABASE=1 .venv/bin/python -m pytest backend/tests/ -q
.venv/bin/python -m pip_audit
```

CI installs the same requirements and treats the backend dependency audit as a required check. It uses a fresh audit environment so obsolete packages left behind by a local upgrade cannot affect the result. There are no advisory exclusions. Docker and CI upgrade the pip bootstrap explicitly before installing dependencies.

Regression coverage includes a synthetic token generated with python-jose 3.4.0, a pre-migration vault ciphertext, JWT expiration/signature/claim validation, real-PostgreSQL login and cookie/CSRF flows, extension Bearer authentication, logout revocation, inactive users and module permissions. HTTP coverage includes uploads that remain in memory or spool to disk, attachment downloads, CRX range responses, CORS and CSRF URL handling. All fixture keys, ciphertexts and credentials are synthetic.

Validated locally on 17 September 2026 with Python 3.12 and PostgreSQL 16.14; the full suite passed 581 tests (87 PostgreSQL integration tests), with 2 existing skips; the fresh-environment audit reported no known vulnerabilities across 105 installed packages. Docker is not installed in that local environment, so the Linux image build and PostgreSQL 17 CI run remain integration checks before release. The requirements retain existing open ranges for unrelated dependencies; the CI audit assesses the graph actually installed at each run.

## Upstream references

- [FastAPI 0.135.1 dependency metadata](https://pypi.org/pypi/fastapi/0.135.1/json) and [Starlette release notes](https://starlette.dev/release-notes/).
- [python-multipart 0.0.31](https://pypi.org/project/python-multipart/0.0.31/).
- [PyJWT usage and claim requirements](https://pyjwt.readthedocs.io/en/stable/usage.html) and [release notes](https://pyjwt.readthedocs.io/en/stable/changelog.html).
- [pytest-asyncio release notes](https://pytest-asyncio.readthedocs.io/en/stable/reference/changelog.html).
- [pip release notes](https://pip.pypa.io/en/stable/news/).
