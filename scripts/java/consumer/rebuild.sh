#!/bin/bash
# Rebuild the consumer Docker image

set -e

cd "$(dirname "$0")/../../.."

echo "Building consumer Docker image..."
docker compose build --no-cache consumer

echo "✓ Consumer image built successfully"
