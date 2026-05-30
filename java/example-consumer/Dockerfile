# Build stage
FROM maven:3.9-eclipse-temurin-17 AS builder

WORKDIR /build

# Copy lib pom and source
COPY lib/pom.xml ./lib/
COPY lib/src ./lib/src

# Copy consumer pom and source
COPY example-consumer/pom.xml ./
COPY example-consumer/src ./src

# Install lib locally then build consumer
RUN cd lib && mvn clean install -DskipTests && \
    cd /build && mvn clean package -DskipTests

# Runtime stage
FROM eclipse-temurin:17-jre-alpine

WORKDIR /app

# Copy built JAR
COPY --from=builder /build/target/anycall-example-consumer-*.jar app.jar

ENTRYPOINT ["java", "-jar", "app.jar"]
