# syntax=docker/dockerfile:1
FROM eclipse-temurin:17-jre-alpine AS supplier
WORKDIR /app
# Fails the build if the jar is absent (run ./scripts/java/rebuild-all.sh first)
COPY example-supplier/target/anycall-example-supplier-*.jar app.jar
ENTRYPOINT ["java", "-jar", "app.jar"]

FROM eclipse-temurin:17-jre-alpine AS consumer
WORKDIR /app
COPY example-consumer/target/anycall-example-consumer-*.jar app.jar
ENTRYPOINT ["java", "-jar", "app.jar"]
