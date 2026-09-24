#!/bin/sh
# Convenience startup script for demoing the movie API under any of the
# four configurations. Usage:
#   ./start.sh [monolith|multi|multi-3x|swarm]   (default: multi)
set -e

CONFIG="${1:-multi}"
ROOT="$(cd "$(dirname "$0")" && pwd)"

if ! docker ps >/dev/null 2>&1; then
    echo "Docker daemon is not running. Run ./scripts/ensure-docker.sh first." >&2
    exit 1
fi

wait_health() {
    echo "Waiting for http://localhost:8000/health ..."
    for i in $(seq 1 60); do
        if curl -sf http://localhost:8000/health >/dev/null 2>&1; then
            echo "Up."
            return 0
        fi
        sleep 1
    done
    echo "Did not become healthy in time." >&2
    return 1
}

case "$CONFIG" in
    monolith)
        docker compose -f "$ROOT/compose/docker-compose.monolith.yml" up -d --build
        wait_health
        ;;
    multi)
        docker compose -f "$ROOT/compose/docker-compose.multi.yml" up -d --build
        wait_health
        ;;
    multi-3x)
        docker compose -f "$ROOT/compose/docker-compose.multi-3x.yml" up -d --build
        wait_health
        ;;
    swarm)
        if [ "$(docker info --format '{{.Swarm.LocalNodeState}}')" != "active" ]; then
            docker swarm init --advertise-addr 127.0.0.1
        fi
        docker compose -f "$ROOT/compose/docker-compose.multi.yml" build app
        docker stack deploy -c "$ROOT/compose/swarm-stack.yml" moviestack
        wait_health
        echo "Scale with: docker service scale moviestack_app=3"
        echo "Tear down with: docker stack rm moviestack"
        ;;
    *)
        echo "Unknown config '$CONFIG'. Use one of: monolith, multi, multi-3x, swarm" >&2
        exit 1
        ;;
esac

cat <<EOF

Movie API is up at http://localhost:8000
Open http://localhost:8000/ in a browser for the full usage guide.

Try:
  curl http://localhost:8000/health
  curl "http://localhost:8000/movies/search?q=toy"
  curl http://localhost:8000/movies/1
  curl -X POST http://localhost:8000/movies/1/rate -H 'Content-Type: application/json' -d '{"rating": 4.5}'
EOF
