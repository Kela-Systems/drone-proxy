#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
USER_HOME="$(eval echo ~$(whoami))"
INFRA_DIR="${USER_HOME}/infra"
CONFIG_FILE="${INFRA_DIR}/config.yml"

echo "==> Installing Drone Proxy"

# Build with host networking (required on Tegra/kernels without iptables raw table)
echo "==> Building Docker image..."
docker build --network=host -t drone-proxy "${SCRIPT_DIR}"

echo "==> Starting Docker container..."
docker compose -f "${SCRIPT_DIR}/docker-compose.yml" up -d

echo ""
echo "==> Done! Drone Proxy is running."
echo "    Config file:  ${CONFIG_FILE}"
echo "    View logs:    docker compose -f ${SCRIPT_DIR}/docker-compose.yml logs -f"
echo "    Stop:         docker compose -f ${SCRIPT_DIR}/docker-compose.yml down"
echo "    UI:           http://localhost:3001"