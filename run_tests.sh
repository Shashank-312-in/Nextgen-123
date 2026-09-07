#!/usr/bin/env bash
# — Run Phase 1 of the NextGen SMS API test suite against your real
# MySQL database and produce an HTML + JUnit XML report.
#
# Usage:
#   1. cp .env.test.example .env.test   (fill in real values, once)
#   2. export SMS_PROJECT_ROOT=/path/to/NextGen_SMS_live_cleaned
#      (the folder containing api/app.py — edit the default below to skip this)
#   3. ./run_tests.sh
#
set -euo pipefail
cd "$(dirname "$0")"

# — Defaults to current directory (the folder containing api/app.py)
: "${SMS_PROJECT_ROOT:=.}"
export SMS_PROJECT_ROOT

if [ ! -f "$SMS_PROJECT_ROOT/api/app.py" ]; then
    echo "ERROR: SMS_PROJECT_ROOT ($SMS_PROJECT_ROOT) does not contain api/app.py"
    echo "Set it correctly: SMS_PROJECT_ROOT=/actual/path ./run_tests.sh"
    exit 1
fi

if [ -f .env.test ]; then
    set -a
    # shellcheck disable=SC1091
    source .env.test
    set +a
else
    echo "WARNING: .env.test not found — copy .env.test.example to .env.test and fill it in."
    echo "Continuing anyway; tests needing DB/role credentials will skip or fail with a clear message."
fi

mkdir -p reports
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"

echo ""
echo "=================================================================="
echo " NextGen SMS API Test Suite — Phase 1 (Auth / Students / Attendance)"
echo " Project under test: $SMS_PROJECT_ROOT"
echo " Run started:         $(date)"
echo "=================================================================="
echo ""

python3 -m pytest tests/ \
    -v \
    --tb=short \
    --html="reports/report_${TIMESTAMP}.html" \
    --self-contained-html \
    --junitxml="reports/junit_${TIMESTAMP}.xml" \
    | tee "reports/console_${TIMESTAMP}.log"

PYTEST_EXIT=${PIPESTATUS[0]}

echo ""
echo "=================================================================="
echo " Reports written to: reports/report_${TIMESTAMP}.html"
echo "                      reports/junit_${TIMESTAMP}.xml"
echo "=================================================================="

python3 build_summary.py "reports/junit_${TIMESTAMP}.xml" "reports/console_${TIMESTAMP}.log" "$TIMESTAMP" || true

exit $PYTEST_EXIT
