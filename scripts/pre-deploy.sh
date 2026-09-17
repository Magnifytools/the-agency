#!/usr/bin/env bash
# Local checks only. Never runs the mutating evaluator against production.
set -euo pipefail
cd "$(dirname "$0")/.."

: "${TEST_DATABASE_URL:?Set TEST_DATABASE_URL to an isolated disposable PostgreSQL test database}"
export REQUIRE_TEST_DATABASE=1
AGENCY_CHECK_PYTHON="${AGENCY_CHECK_PYTHON:-backend/venv/bin/python}"

"$AGENCY_CHECK_PYTHON" -m pytest backend/tests/ -q --tb=short
(cd frontend && npm run test && npm run build)
git diff --check
echo "Pre-deploy checks passed (no production writes)."
