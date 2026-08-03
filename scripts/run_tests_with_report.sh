#!/usr/bin/env bash
# ───────────────────────────────────────────────────────────────────
# scripts/run_tests_with_report.sh
# ───────────────────────────────────────────────────────────────────
# Runs the project's full local quality gate (pytest, ruff, mypy) and
# writes a persisted, human-readable summary to test-results/latest.md.
#
# WHY THIS EXISTS: `pytest tests/ -v`, `ruff check .`, and `mypy src/`
# only ever printed to whatever console/CI log happened to be running
# them. That log scrolls away and CI logs expire — there was no
# durable, easy-to-skim record of "did the last run actually pass,
# and if not, what broke". This script produces that record every
# time it's run, locally or in CI.
#
# USAGE:
#   ./scripts/run_tests_with_report.sh
#
# OUTPUT:
#   test-results/latest.md   — regenerated every run (gitignored, see
#                               test-results/.gitignore). Contains a
#                               timestamp, one-line pass/fail status
#                               per tool, pass/fail counts for pytest,
#                               and the list of any failing tests.
#
# EXIT CODE: non-zero if any of pytest/ruff/mypy failed, so this
# script can be used as a CI gate directly if desired. In this repo's
# CI workflows it's wired up with `continue-on-error: true` (the
# report is uploaded either way; see .github/workflows/).
# ───────────────────────────────────────────────────────────────────
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

RESULTS_DIR="test-results"
REPORT_FILE="$RESULTS_DIR/latest.md"
PYTEST_LOG="$RESULTS_DIR/.pytest-output.txt"
PYTEST_JUNIT="$RESULTS_DIR/.pytest-junit.xml"
RUFF_LOG="$RESULTS_DIR/.ruff-output.txt"
MYPY_LOG="$RESULTS_DIR/.mypy-output.txt"

mkdir -p "$RESULTS_DIR"

TIMESTAMP="$(date -u +"%Y-%m-%d %H:%M:%S UTC")"

# ── Run pytest (JUnit XML gives us reliable pass/fail counts + names) ──
pytest tests/ -v --junitxml="$PYTEST_JUNIT" >"$PYTEST_LOG" 2>&1
PYTEST_EXIT=$?

# ── Run ruff ──────────────────────────────────────────────────────
ruff check . >"$RUFF_LOG" 2>&1
RUFF_EXIT=$?

# ── Run mypy ──────────────────────────────────────────────────────
mypy src/ >"$MYPY_LOG" 2>&1
MYPY_EXIT=$?

# ── Build the markdown report ────────────────────────────────────
python3 "$REPO_ROOT/scripts/_render_test_report.py" \
  --timestamp "$TIMESTAMP" \
  --report-file "$REPORT_FILE" \
  --pytest-exit "$PYTEST_EXIT" \
  --pytest-junit "$PYTEST_JUNIT" \
  --pytest-log "$PYTEST_LOG" \
  --ruff-exit "$RUFF_EXIT" \
  --ruff-log "$RUFF_LOG" \
  --mypy-exit "$MYPY_EXIT" \
  --mypy-log "$MYPY_LOG"

echo "Wrote $REPORT_FILE"

# ── Overall exit code: non-zero if anything failed ─────────────────
if [ "$PYTEST_EXIT" -ne 0 ] || [ "$RUFF_EXIT" -ne 0 ] || [ "$MYPY_EXIT" -ne 0 ]; then
  exit 1
fi
exit 0
