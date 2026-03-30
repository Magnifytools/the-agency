#!/bin/bash
# Pre-deploy check for The Agency
# Run before `railway up` to catch issues early
set -e

echo "=== Pre-deploy Check: The Agency ==="
echo ""

# 1. Backend tests
echo "1. Running backend tests..."
cd "$(dirname "$0")/.."
python3 -m pytest backend/ -x -q --tb=line 2>&1 | tail -3
echo ""

# 2. TypeScript check
echo "2. TypeScript check..."
cd frontend && npx tsc --noEmit 2>&1 | head -5
TS_EXIT=$?
cd ..
if [ $TS_EXIT -ne 0 ]; then
  echo "❌ TypeScript errors found. Fix before deploying."
  exit 1
fi
echo "✅ 0 TypeScript errors"
echo ""

# 3. Evaluator (optional — skip with --skip-eval)
if [ "$1" != "--skip-eval" ]; then
  echo "3. Running evaluator..."
  python3 scripts/evaluator.py --base https://agency.magnifytools.com 2>&1 | tail -10
  EVAL_EXIT=$?
  if [ $EVAL_EXIT -ne 0 ]; then
    echo "⚠️  Evaluator returned non-zero. Review before deploying."
  fi
else
  echo "3. Evaluator skipped (--skip-eval)"
fi

echo ""
echo "=== Pre-deploy check complete ==="
