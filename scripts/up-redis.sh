#!/bin/bash
# Start Redis container

set -e

cd "$(dirname "$0")/.."

echo "Starting Redis..."
docker compose up -d redis

echo "Waiting for Redis to be healthy..."
docker compose exec -T redis redis-cli ping

echo "✓ Redis is ready"
