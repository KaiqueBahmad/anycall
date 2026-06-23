#!/bin/bash
cd "$(dirname "$0")"
mvn package -q -DskipTests
java -cp example-consumer/target/anycall-example-consumer.jar dev.kaiquebt.anycall.example.runners.InvalidPayloadClient
