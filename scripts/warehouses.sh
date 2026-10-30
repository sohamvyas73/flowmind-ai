#!/usr/bin/env bash
# Start / stop / check a local demo warehouse for FlowMind's pushdown.
#   ./scripts/warehouses.sh start clickhouse | status | stop clickhouse
set -euo pipefail
cd "$(dirname "$0")/.."
F=docker-compose.warehouses.yml
up() { curl -fsS -m 3 -o /dev/null "http://localhost:8123/ping" 2>/dev/null; }
case "${1:-}" in
  start) [[ "${2:-}" == "clickhouse" ]] || { echo "Only 'clickhouse' can be started here. Other warehouses are cloud services (add a connection) or your own PostgreSQL." >&2; exit 2; }
         docker compose -f "$F" --profile clickhouse up -d
         for i in $(seq 1 40); do up && { echo "ClickHouse is up at http://localhost:8123 (user flowmind / password flowmind-demo / database shop)"; echo "Next: Connections → New connection → ClickHouse (Read & write; an admin must allow-list 'localhost'), then 'Load example tables'."; exit 0; }; sleep 2; done
         echo "ClickHouse did not become ready in 80 s — check: docker compose -f $F logs clickhouse" >&2; exit 1;;
  stop)  docker compose -f "$F" --profile clickhouse stop;;
  status) if up; then echo "clickhouse: running (port 8123)"; else echo "clickhouse: not running"; fi;;
  *) sed -n '2,3p' "$0"; exit 2;;
esac
