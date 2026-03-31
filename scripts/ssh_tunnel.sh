#!/usr/bin/env bash
# Open an SSH tunnel to a remote GPU instance for vLLM access.
#
# Usage:
#   ./scripts/ssh_tunnel.sh
#   SSH_HOST=user@gpu-host SSH_KEY=~/.ssh/id_ed25519 ./scripts/ssh_tunnel.sh
#
# The tunnel forwards local port LOCAL_PORT to REMOTE_PORT on the remote host,
# making vLLM accessible at http://localhost:LOCAL_PORT.

set -euo pipefail

SSH_HOST="${SSH_HOST:?Set SSH_HOST (e.g. ubuntu@192.168.1.100)}"
SSH_KEY="${SSH_KEY:-~/.ssh/id_ed25519}"
LOCAL_PORT="${LOCAL_PORT:-8081}"
REMOTE_PORT="${REMOTE_PORT:-8000}"

echo "=== SSH Tunnel ==="
echo "Remote:     $SSH_HOST"
echo "Key:        $SSH_KEY"
echo "Forwarding: localhost:$LOCAL_PORT -> remote:$REMOTE_PORT"
echo ""
echo "vLLM will be accessible at http://localhost:$LOCAL_PORT"
echo "Press Ctrl+C to close the tunnel."
echo ""

ssh -N -L "${LOCAL_PORT}:localhost:${REMOTE_PORT}" \
    -i "$SSH_KEY" \
    -o StrictHostKeyChecking=accept-new \
    -o ServerAliveInterval=30 \
    -o ServerAliveCountMax=3 \
    "$SSH_HOST"
