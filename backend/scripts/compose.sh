#!/usr/bin/env bash
set -euo pipefail

BACKEND_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODE="${1:-production}"
if [[ "$MODE" == "prod" ]]; then MODE="production"; fi
if [[ "$MODE" != "dev" && "$MODE" != "production" ]]; then
  echo "usage: $0 [dev|production] [init-env|docker compose arguments...]" >&2
  exit 2
fi
shift || true

ENV_NAMES=(app database kafka cache storage clickhouse logging gateway engine auth frontend build)

init_env() {
  local name source target
  for name in "${ENV_NAMES[@]}"; do
    source="$BACKEND_DIR/dotenv/$MODE/.env.$name.example"
    target="$BACKEND_DIR/dotenv/$MODE/.env.$name"
    if [[ ! -f "$target" ]]; then
      cp "$source" "$target"
      echo "created dotenv/$MODE/.env.$name"
    fi
  done
}

validate_production_secrets() {
  local spec name key minimum file value
  for name in auth cache clickhouse database logging storage; do
    file="$BACKEND_DIR/dotenv/production/.env.$name"
    if grep -Eqi '^[^#]*change-me' "$file"; then
      echo "refusing production startup: replace every placeholder in dotenv/production/.env.$name" >&2
      exit 1
    fi
  done
  local specs=(
    "auth:MONKEYOCR_API_KEY_PEPPER:32"
    "cache:REDIS_PASSWORD:16"
    "clickhouse:CLICKHOUSE_PASSWORD:16"
    "database:POSTGRES_PASSWORD:16"
    "logging:LOGGING_SERVICE_TOKEN:32"
    "storage:MINIO_SECRET_KEY:16"
    "storage:STORAGE_SERVICE_TOKEN:32"
  )
  for spec in "${specs[@]}"; do
    IFS=: read -r name key minimum <<<"$spec"
    file="$BACKEND_DIR/dotenv/production/.env.$name"
    value="$(awk -F= -v key="$key" '$1 == key {sub(/^[^=]*=/, ""); print; exit}' "$file")"
    if [[ -z "${value//[[:space:]]/}" || ${#value} -lt minimum || "$value" == *change-me* ]]; then
      echo "refusing production startup: $key in dotenv/production/.env.$name must be a non-placeholder secret of at least $minimum characters" >&2
      exit 1
    fi
  done
}

has_compose_command() {
  local candidate
  for candidate in "$@"; do
    case "$candidate" in
      up|start|restart|create|run|watch|scale|build)
        return 0
        ;;
    esac
  done
  return 1
}

has_start_command() {
  local candidate
  for candidate in "$@"; do
    case "$candidate" in
      up|start|restart|create|run|watch|scale)
        return 0
        ;;
    esac
  done
  return 1
}

if [[ "${1:-}" == "init-env" ]]; then
  init_env
  exit 0
fi

compose_args=()
for name in "${ENV_NAMES[@]}"; do
  env_file="$BACKEND_DIR/dotenv/$MODE/.env.$name"
  if [[ ! -f "$env_file" ]]; then
    echo "missing dotenv/$MODE/.env.$name; run: $0 $MODE init-env" >&2
    exit 1
  fi
  compose_args+=(--env-file "$env_file")
done

if [[ "$MODE" == "dev" ]]; then
  compose_files=(
    infrastructure/docker/compose/dev/base.yml
    infrastructure/docker/compose/dev/infrastructure.yml
    infrastructure/docker/compose/dev/application.yml
  )
else
  compose_files=(
    infrastructure/docker/compose/production/base.yml
    infrastructure/docker/compose/production/application.yml
    infrastructure/docker/compose/production/engine-hps.yml
  )
fi

for file in "${compose_files[@]}"; do
  compose_args+=(-f "$BACKEND_DIR/$file")
done

if [[ "$MODE" == "production" ]] && has_start_command "$@"; then
  validate_production_secrets
fi

if [[ "$MODE" == "production" && "${MONKEYOCR_ENABLE_HPS:-1}" == "1" ]]; then
  if has_compose_command "$@" && [[ ! -f "$BACKEND_DIR/infrastructure/paddleocr-hps/runtime/gateway.Dockerfile" ]]; then
    echo "PaddleOCR HPS is not prepared; run backend/scripts/prepare_hps.sh" >&2
    exit 1
  fi
  compose_args+=(--profile hps)
fi

exec docker compose "${compose_args[@]}" "$@"
