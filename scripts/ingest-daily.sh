#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

exec pnpm --filter @maiven/db exec varlock run -- uv run --project ../../pipelines/ingest federal-register-ingest
