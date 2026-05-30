#!/bin/bash
# Run the consumer (one-shot execution)

set -e

cd "$(dirname "$0")/../../.."

if ! docker compose exec -T redis redis-cli ping > /dev/null 2>&1; then
    echo "Error: Redis is not running. Start it with: ./scripts/up-redis.sh"
    exit 1
fi

if ! docker compose exec -T supplier wget -qO- http://localhost:8080/health > /dev/null 2>&1; then
    echo "Error: Supplier is not running. Start it with: ./scripts/java/supplier/up.sh"
    exit 1
fi

echo "Running consumer..."
docker compose run --rm consumer

echo "✓ Consumer completed"
