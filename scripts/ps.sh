#!/bin/bash
# Start Redis container

set -e

cd "$(dirname "$0")/.."

docker compose ps
