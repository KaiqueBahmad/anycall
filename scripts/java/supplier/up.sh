#!/bin/bash
# Start supplier container (requires Redis running)

set -e

cd "$(dirname "$0")/../../.."

if ! docker compose exec -T redis redis-cli ping > /dev/null 2>&1; then
    echo "Error: Redis is not running. Start it with: ./scripts/up-redis.sh"
    exit 1
fi

echo "Starting supplier..."
docker compose up -d supplier

echo "Waiting for supplier to start..."
sleep 3

echo "✓ Supplier started"
