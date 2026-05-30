#!/bin/bash
# Run the consumer (one-shot execution)

set -e

cd "$(dirname "$0")/../../.."

docker compose up consumer

echo "✓ Consumer completed"
