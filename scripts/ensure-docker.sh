#!/bin/sh
# Makes sure the Docker daemon is running and enabled at boot.
# Needs sudo, so it must be run interactively (not from an automated sandboxed session).
set -e

if docker ps >/dev/null 2>&1; then
    echo "Docker is already running."
    exit 0
fi

echo "Docker daemon not running - starting it (will prompt for your password)..."
sudo systemctl enable --now docker

echo "Waiting for the daemon socket..."
for i in $(seq 1 20); do
    if docker ps >/dev/null 2>&1; then
        echo "Docker is up."
        exit 0
    fi
    sleep 0.5
done

echo "Docker still not responding after starting the service - check 'systemctl status docker'." >&2
exit 1
