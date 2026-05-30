#!/bin/bash
# Stop all Docker containers and services

set -e

cd "$(dirname "$0")/.."

echo "Stopping all services..."
docker compose down --remove-orphans -v

echo "✓ All services stopped"
