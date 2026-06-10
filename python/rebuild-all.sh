#!/bin/bash
set -e
cd "$(dirname "$0")/.."   # -> repo root

prefix() {
  local label=$1; shift
  "$@" 2>&1 | sed "s/^/[$label] /"
  return ${PIPESTATUS[0]}
}

set +e
prefix uv uv --project python sync
UV_STATUS=$?

SUPPLIER_STATUS=0
CONSUMER_STATUS=0
if [ $UV_STATUS -eq 0 ]; then
  prefix python-supplier docker compose build python-supplier; SUPPLIER_STATUS=$?
  prefix python-consumer docker compose build python-consumer; CONSUMER_STATUS=$?
fi

echo ""
echo "----------------------------------------"
[ $UV_STATUS -eq 0 ]      && echo "OK  uv sync" || echo "FAIL uv sync"
[ $SUPPLIER_STATUS -eq 0 ] && echo "OK  supplier docker" || echo "FAIL supplier docker"
[ $CONSUMER_STATUS -eq 0 ] && echo "OK  consumer docker" || echo "FAIL consumer docker"
echo "----------------------------------------"
[ $UV_STATUS -eq 0 ] && [ $SUPPLIER_STATUS -eq 0 ] && [ $CONSUMER_STATUS -eq 0 ] || exit 1
