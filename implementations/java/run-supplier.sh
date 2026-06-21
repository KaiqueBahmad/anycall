#!/bin/bash
cd "$(dirname "$0")"
mvn package -q -DskipTests
java -cp example-supplier/target/anycall-example-supplier.jar dev.kaiquebt.anycall.example.SupplierApplication
