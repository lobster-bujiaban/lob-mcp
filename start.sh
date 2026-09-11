#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

if [[ ! -f .env ]]; then
  echo "错误：未找到 $ROOT_DIR/.env" >&2
  exit 1
fi

if ! grep -q '^LOB_MCP_MASTER_KEY=' .env; then
  echo "正在生成持久化凭据主密钥..."
  MASTER_KEY="$(uv run python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"
  printf '\nLOB_MCP_MASTER_KEY=%s\n' "$MASTER_KEY" >> .env
fi

if [[ ! -f web/dist/index.html ]]; then
  echo "未找到前端构建产物，正在构建 React 管理台..."
  npm --prefix web install
  npm --prefix web run build
fi

exec uv run --env-file .env lob-mcp serve-admin "$@"
