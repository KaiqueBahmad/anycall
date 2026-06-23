#!/bin/bash
set -e
cd "$(dirname "$0")/../.."   # -> repo root

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
  prefix mvn mvn -f implementations/java/pom.xml clean install -DskipTests -T1C -pl "$CHANGED" -amd
else
  prefix mvn mvn -f implementations/java/pom.xml clean install -DskipTests -T1C
fi
MVN_STATUS=$?

echo ""
echo "----------------------------------------"
[ $MVN_STATUS -eq 0 ] && echo "OK  maven (reactor)" || echo "FAIL maven (reactor)"
echo "----------------------------------------"
[ $MVN_STATUS -eq 0 ] || exit 1
