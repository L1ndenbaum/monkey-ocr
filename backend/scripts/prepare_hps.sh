#!/usr/bin/env bash
set -euo pipefail

BACKEND_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENGINE_ENV="$BACKEND_DIR/dotenv/production/.env.engine"
BUILD_ENV="$BACKEND_DIR/dotenv/production/.env.build"
if [[ ! -f "$ENGINE_ENV" ]]; then
  echo "missing dotenv/production/.env.engine; run backend/scripts/compose.sh production init-env" >&2
  exit 1
fi
if [[ ! -f "$BUILD_ENV" ]]; then
  echo "missing dotenv/production/.env.build; run backend/scripts/compose.sh production init-env" >&2
  exit 1
fi
set -a
# shellcheck disable=SC1090
source "$ENGINE_ENV"
# shellcheck disable=SC1090
source "$BUILD_ENV"
set +a

# BUILD_* is the repository-owned dotenv namespace. Export conventional names
# only for this preparation process so git/curl/wget/pip used upstream honor it.
export HTTP_PROXY="${BUILD_HTTP_PROXY:-${HTTP_PROXY:-}}"
export HTTPS_PROXY="${BUILD_HTTPS_PROXY:-${HTTPS_PROXY:-}}"
export NO_PROXY="${BUILD_NO_PROXY:-${NO_PROXY:-}}"
export http_proxy="$HTTP_PROXY"
export https_proxy="$HTTPS_PROXY"
export no_proxy="$NO_PROXY"
export PIP_INDEX_URL="${BUILD_PYPI_INDEX_URL:-${PIP_INDEX_URL:-https://pypi.org/simple}}"

HPS_DIR="$BACKEND_DIR/infrastructure/paddleocr-hps"
SOURCE_DIR="$HPS_DIR/source"
RUNTIME_DIR="$HPS_DIR/runtime"
PADDLEOCR_REPOSITORY="${PADDLEOCR_REPOSITORY:-https://github.com/PaddlePaddle/PaddleOCR.git}"
PADDLEOCR_REF="${PADDLEOCR_REF:-211989f046cc1878460f9e65574690c00a127a1a}"

if [[ ! -d "$SOURCE_DIR/.git" ]]; then
  mkdir -p "$HPS_DIR"
  git clone --filter=blob:none --no-checkout "$PADDLEOCR_REPOSITORY" "$SOURCE_DIR"
fi

git -C "$SOURCE_DIR" fetch --depth 1 origin "$PADDLEOCR_REF"
git -C "$SOURCE_DIR" checkout --detach FETCH_HEAD

rm -rf "$RUNTIME_DIR"
mkdir -p "$RUNTIME_DIR"
cp -a "$SOURCE_DIR/deploy/paddleocr_vl_docker/hps/." "$RUNTIME_DIR/"

cp "$ENGINE_ENV" "$RUNTIME_DIR/.env"
(
  cd "$RUNTIME_DIR"
  bash prepare.sh
)

echo "PaddleOCR-VL HPS prepared in $RUNTIME_DIR"
