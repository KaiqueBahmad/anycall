#!/bin/bash
# Rebuild the supplier Docker image

set -e

cd "$(dirname "$0")/../../.."

echo "Building supplier Docker image..."
docker compose build --no-cache supplier

echo "✓ Supplier image built successfully"
