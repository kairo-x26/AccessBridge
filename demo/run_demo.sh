#!/usr/bin/env bash
# Start the AccessBridge demo: a freshly seeded synthetic clinic, the API, the background
# worker and the web app. Ctrl+C stops everything.
#
#   ./demo/run_demo.sh            # then open http://localhost:3000
#   ./demo/run_demo.sh --keep     # keep yesterday's demo data instead of reseeding
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DB="sqlite:///${ROOT}/backend/var/demo.db"
export AB_DATABASE_URL="$DB" AB_STORAGE_DIR="${ROOT}/backend/var/demo-documents"
export AB_LOG_LEVEL=WARNING

need() { command -v "$1" >/dev/null || { echo "Install $1 first (see docs/DEVELOPER_GUIDE.md)."; exit 1; }; }
need uv
need pnpm

# A second copy would reseed the database underneath the running one.
for port in 8000 3000; do
  if lsof -ti "tcp:${port}" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "Port ${port} is already in use. Is the demo already running? Stop it first (Ctrl+C in its terminal)."
    exit 1
  fi
done

cd "$ROOT/backend"
uv sync --quiet --all-extras
if [[ "${1:-}" != "--keep" ]]; then
  rm -rf "${ROOT}/backend/var/demo.db"* "${ROOT}/backend/var/demo-documents"
  echo "Seeding the synthetic Riverbend Community Health network…"
  uv run python -m app.seed --reset >/dev/null
fi

cd "$ROOT/frontend"
pnpm install --silent --frozen-lockfile

pids=()
# uv and pnpm start the real servers as grandchildren, so stop each child's whole tree.
killtree() {
  local child
  for child in $(pgrep -P "$1" 2>/dev/null); do killtree "$child"; done
  kill -TERM "$1" 2>/dev/null || true
}
cleanup() {
  trap - EXIT INT TERM
  echo; echo "Stopping demo…"
  for pid in "${pids[@]}"; do killtree "$pid"; done
}
trap cleanup EXIT INT TERM

(cd "$ROOT/backend" && uv run uvicorn app.main:app --port 8000 --log-level warning) & pids+=($!)
(cd "$ROOT/backend" && uv run python -m app.workers.run) & pids+=($!)
(cd "$ROOT/frontend" && BACKEND_URL=http://127.0.0.1:8000 NEXT_PUBLIC_DEMO=1 pnpm exec next dev --port 3000) & pids+=($!)

for _ in $(seq 1 60); do
  curl -fs http://127.0.0.1:8000/health >/dev/null 2>&1 && curl -fs http://localhost:3000/login >/dev/null 2>&1 && break
  sleep 1
done

cat <<MSG

  AccessBridge demo is running (synthetic data only)

  Web app     http://localhost:3000
  API docs    http://127.0.0.1:8000/docs

  Sign in to organization "riverbend" with password "Demo-Password-2026" as:
    priya.coordinator@riverbend.example.org   referral coordinator
    grace.navigator@riverbend.example.org     patient navigator
    dana.admin@riverbend.example.org          administrator
    amara.clinician@riverbend.example.org     clinician
    ivy.security@riverbend.example.org        security administrator

  Narrated walkthrough in another terminal:
    cd backend && uv run python ../demo/scenario.py

MSG
wait
