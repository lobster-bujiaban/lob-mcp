#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

if [[ ! -f .env ]]; then
  echo "错误：未找到 $ROOT_DIR/.env" >&2
  exit 1
fi

if [[ ! -f web/dist/index.html ]]; then
  echo "未找到前端构建产物，正在构建 React 管理台..."
  npm --prefix web install
  npm --prefix web run build
fi

exec uv run --env-file .env lob-mcp serve-admin "$@"
