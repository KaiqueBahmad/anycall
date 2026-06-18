#!/bin/bash
cd "$(dirname "$0")"
mvn package -q -DskipTests
java -cp example-consumer/target/anycall-example-consumer-0.0.1-SNAPSHOT.jar dev.kaiquebt.anycall.example.runners.InvalidPayloadClient
