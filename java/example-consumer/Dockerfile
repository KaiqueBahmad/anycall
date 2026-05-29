# Build stage
FROM maven:3.9-eclipse-temurin-17 AS builder

WORKDIR /build

# Copy parent pom and lib
COPY ../lib/pom.xml ../lib/pom.xml
COPY ../lib/src ../lib/src

# Copy consumer example
COPY pom.xml .
COPY src ./src

# Install lib locally then build consumer
RUN cd ../lib && mvn clean install -DskipTests && \
    cd /build && mvn clean package -DskipTests

# Runtime stage
FROM eclipse-temurin:17-jre-alpine

WORKDIR /app

# Copy built JAR
COPY --from=builder /build/target/anycall-example-consumer-*.jar app.jar

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD wget --no-verbose --tries=1 --spider http://localhost:8080/actuator/health || exit 1

EXPOSE 8080

ENTRYPOINT ["java", "-jar", "app.jar"]
