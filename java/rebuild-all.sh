#!/bin/bash
set -e
cd "$(dirname "$0")/.."   # -> repo root

prefix() {
  local label=$1; shift
  "$@" 2>&1 | sed "s/^/[$label] /"
  return ${PIPESTATUS[0]}
}

# Usage:
#   ./rebuild-all.sh         full reactor build
#   ./rebuild-all.sh lib     rebuild lib + its dependents only (-amd)
CHANGED="$1"

set +e
if [ -n "$CHANGED" ]; then
  prefix mvn mvn -f java/pom.xml clean install -DskipTests -T1C -pl "$CHANGED" -amd
else
  prefix mvn mvn -f java/pom.xml clean install -DskipTests -T1C
fi
MVN_STATUS=$?

SUPPLIER_STATUS=0
CONSUMER_STATUS=0
if [ $MVN_STATUS -eq 0 ]; then
  # No --no-cache. clean above guarantees one fresh jar in each target/.
  prefix supplier docker compose build supplier; SUPPLIER_STATUS=$?
  prefix consumer docker compose build consumer; CONSUMER_STATUS=$?
fi

echo ""
echo "----------------------------------------"
[ $MVN_STATUS -eq 0 ]      && echo "OK  maven (reactor)" || echo "FAIL maven (reactor)"
[ $SUPPLIER_STATUS -eq 0 ] && echo "OK  supplier docker" || echo "FAIL supplier docker"
[ $CONSUMER_STATUS -eq 0 ] && echo "OK  consumer docker" || echo "FAIL consumer docker"
echo "----------------------------------------"
[ $MVN_STATUS -eq 0 ] && [ $SUPPLIER_STATUS -eq 0 ] && [ $CONSUMER_STATUS -eq 0 ] || exit 1
