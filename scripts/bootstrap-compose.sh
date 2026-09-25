#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

usage() {
  cat <<'EOF'
Usage:
  ./scripts/bootstrap-compose.sh [--documents N]
  ./scripts/bootstrap-compose.sh ingest [ingest arguments...]
  ./scripts/bootstrap-compose.sh stop

The default flow builds the app and ingest images, starts PostgreSQL, applies
migrations, ingests Federal Register EPA rules, then starts the web app.
Set COMPOSE_PROJECT_NAME to isolate this stack from other Compose projects.
EOF
}

action="bootstrap"
if [[ "${1:-}" == "ingest" || "${1:-}" == "stop" || "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  action="$1"
  shift
fi

case "$action" in
  bootstrap)
    documents="${INGEST_MAX_UNIQUE_DOCUMENTS:-100}"
    if [[ "${1:-}" == "--documents" ]]; then
      documents="${2:?--documents requires a positive integer}"
      shift 2
    fi
    if (($# > 0)); then
      usage >&2
      exit 2
    fi

    docker compose build web bootstrap ingest
    docker compose up -d postgres
    docker compose up -d bootstrap
    wait_status=0
    docker compose wait bootstrap || wait_status=$?
    bootstrap_id="$(docker compose ps --all --quiet bootstrap | head -n 1)"
    if [[ -z "$bootstrap_id" ]]; then
      echo "bootstrap container was not found" >&2
      exit 1
    fi
    bootstrap_status="$(docker inspect --format '{{.State.ExitCode}}' "$bootstrap_id")"
    if [[ "$bootstrap_status" != "0" ]]; then
      docker compose logs bootstrap >&2
      exit "$bootstrap_status"
    fi
    if ((wait_status != 0)); then
      docker compose logs bootstrap >&2
      exit "$wait_status"
    fi

    docker compose run --build --rm ingest --max-unique-documents "$documents"
    docker compose up -d
    printf '\nWeb app: http://127.0.0.1:3000\n'
    ;;
  ingest)
    docker compose run --build --rm ingest "$@"
    ;;
  stop)
    docker compose stop
    ;;
  -h|--help)
    usage
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac
