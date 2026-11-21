#!/usr/bin/env bash
# Smoke test for a running stack, through the frontend's nginx (the same path a
# browser uses): static app, /api/health, /api/docs, then a real upload polled
# until the job finishes. Used by CI against the mock compose; also works against
# the real-model stack (use a longer timeout).
#
# Usage:  ./scripts/smoke_test.sh [base_url] [timeout_seconds]
#         ./scripts/smoke_test.sh http://127.0.0.1:8080 120
# Needs: curl, python3 (for JSON parsing; present on GitHub runners and in the backend venv).
set -euo pipefail

BASE="${1:-http://127.0.0.1:8080}"
TIMEOUT="${2:-120}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SAMPLES="$REPO_ROOT/sample_pdfs/adversarial"
PY="${PYTHON:-python3}"
command -v "$PY" >/dev/null 2>&1 || PY=python

json() { "$PY" -c "import sys, json; d = json.load(sys.stdin); print($1)"; }
fail() { echo "SMOKE TEST FAILED: $*" >&2; exit 1; }

echo "== frontend: index.html"
curl -fsS "$BASE/" | grep -q '<div id="root">' || fail "index.html not served"

echo "== /api/health through nginx"
HEALTH="$(curl -fsS "$BASE/api/health")"
echo "   $HEALTH"

echo "== /api/docs and /api/openapi.json through nginx"
curl -fsS -o /dev/null "$BASE/api/docs" || fail "/api/docs not reachable"
curl -fsS "$BASE/api/openapi.json" | json "d['info']['title']" >/dev/null || fail "openapi.json"

echo "== upload: two PDFs (one with a vector chart, one with an injection attempt)"
START=$(date +%s)
CREATED="$(curl -fsS -F "files=@$SAMPLES/vector_chart.pdf" -F "files=@$SAMPLES/prompt_injection.pdf" \
  -F "profile=general" "$BASE/api/jobs")"
JOB_ID="$(echo "$CREATED" | json "d['job_id']")"
echo "   job $JOB_ID accepted=$(echo "$CREATED" | json "len(d['accepted'])")"

echo "== polling until the job finishes (timeout ${TIMEOUT}s)"
STATUS=queued
while :; do
  STATUS="$(curl -fsS "$BASE/api/jobs/$JOB_ID" | json "d['status']")"
  case "$STATUS" in completed|partial|failed) break ;; esac
  (( $(date +%s) - START > TIMEOUT )) && fail "timed out with status '$STATUS'"
  sleep 2
done
ELAPSED=$(( $(date +%s) - START ))

JOB="$(curl -fsS "$BASE/api/jobs/$JOB_ID")"
echo "   status=$STATUS after ${ELAPSED}s; documents: $(echo "$JOB" | json "[x['status'] for x in d['documents']]")"
[ "$STATUS" = completed ] || fail "job ended '$STATUS'"
echo "$JOB" | json "'consolidated report: ' + ('yes' if d['consolidated'] else 'NO')"
echo "$JOB" | json "d['consolidated'] is not None" | grep -q True || fail "no consolidated report"

echo "== invalid upload is rejected with the error envelope"
CODE="$(curl -sS -o /dev/null -w '%{http_code}' -F "files=@$SAMPLES/fake_pdf.pdf" "$BASE/api/jobs")"
[ "$CODE" = 400 ] || fail "expected 400 for an all-invalid upload, got $CODE"

echo "SMOKE TEST PASSED (job completed in ${ELAPSED}s)"
