#!/usr/bin/env bash
# Start / stop / check the optional vector databases for FlowMind retrieval.
#   ./scripts/vectorstores.sh list
#   ./scripts/vectorstores.sh start qdrant|weaviate|chroma
#   ./scripts/vectorstores.sh status
#   ./scripts/vectorstores.sh stop qdrant|weaviate|chroma
set -euo pipefail
cd "$(dirname "$0")/.."
F=docker-compose.vectorstores.yml
declare -A PORT=( [qdrant]=6333 [weaviate]=8080 [chroma]=8001 )
declare -A PATHS=( [qdrant]=/ [weaviate]=/v1/.well-known/ready [chroma]=/api/v2/heartbeat )

need() { [[ -n "${PORT[$1]:-}" ]] || { echo "Unknown store '$1'. Choose: qdrant, weaviate, chroma (pgvector needs no container)." >&2; exit 2; }; }
up()   { curl -fsS -m 3 -o /dev/null "http://localhost:${PORT[$1]}${PATHS[$1]}" 2>/dev/null; }

case "${1:-}" in
  list)
    echo "pgvector   your existing PostgreSQL (no container) — CREATE EXTENSION vector;"
    echo "qdrant     http://localhost:6333   fast, filtering, production"
    echo "weaviate   http://localhost:8080   hybrid search, rich schemas"
    echo "chroma     http://localhost:8001   simple, great for prototypes";;
  start) need "${2:-}"; docker compose -f "$F" --profile "$2" up -d
         for i in $(seq 1 30); do up "$2" && { echo "$2 is up at http://localhost:${PORT[$2]}"; echo "Next: Connections → New connection → $2 → URL http://localhost:${PORT[$2]} (an admin must allow-list 'localhost')."; exit 0; }; sleep 2; done
         echo "$2 did not become ready in 60 s — check: docker compose -f $F logs $2" >&2; exit 1;;
  stop)  need "${2:-}"; docker compose -f "$F" --profile "$2" stop;;
  status) for s in qdrant weaviate chroma; do if up "$s"; then echo "$s: running (port ${PORT[$s]})"; else echo "$s: not running"; fi; done;;
  *) sed -n '2,7p' "$0"; exit 2;;
esac
