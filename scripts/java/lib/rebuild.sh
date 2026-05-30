#!/bin/bash
# Rebuild the AnyCall library

set -e

cd "$(dirname "$0")/../../.."

echo "Building AnyCall library..."
mvn -f java/lib/pom.xml clean install -DskipTests

echo "✓ Library built successfully"
