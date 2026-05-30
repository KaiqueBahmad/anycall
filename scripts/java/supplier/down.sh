#!/bin/bash
# Stop supplier container

set -e

cd "$(dirname "$0")/../../.."

echo "Stopping supplier..."
docker compose down supplier --remove-orphans -v

echo "✓ Supplier stopped"
