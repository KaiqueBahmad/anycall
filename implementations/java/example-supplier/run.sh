#!/bin/bash
set -e

# repo root (parent pom.xml)
cd "$(dirname "$0")/.."

./example-supplier/mvnw -pl example-supplier -am install -DskipTests

java -jar example-supplier/target/anycall-example-supplier.jar
