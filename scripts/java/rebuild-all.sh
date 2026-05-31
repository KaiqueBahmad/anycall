#!/bin/bash
set -e
cd "$(dirname "$0")/../.."

prefix() {
  local label=$1
  shift
  "$@" 2>&1 | sed "s/^/[$label] /"
  return ${PIPESTATUS[0]}
}

prefix lib      mvn -f java/lib/pom.xml clean install -DskipTests &
PID_LIB=$!
prefix supplier mvn -f java/example-supplier/pom.xml clean install -DskipTests &
PID_SUPPLIER=$!
prefix consumer mvn -f java/example-consumer/pom.xml clean install -DskipTests &
PID_CONSUMER=$!

set +e
wait $PID_LIB;      LIB_STATUS=$?
wait $PID_SUPPLIER; SUPPLIER_STATUS=$?
wait $PID_CONSUMER; CONSUMER_STATUS=$?

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
[ $LIB_STATUS -eq 0 ]      && echo "✓ lib"      || echo "✗ lib"
[ $SUPPLIER_STATUS -eq 0 ] && echo "✓ supplier" || echo "✗ supplier"
[ $CONSUMER_STATUS -eq 0 ] && echo "✓ consumer" || echo "✗ consumer"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

[ $LIB_STATUS -eq 0 ] && [ $SUPPLIER_STATUS -eq 0 ] && [ $CONSUMER_STATUS -eq 0 ] || exit 1
