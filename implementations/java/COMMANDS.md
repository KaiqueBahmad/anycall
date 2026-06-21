# Comandos úteis

All commands must be run from the `implementations/java/` directory (reactor root).

## Compilar o projeto
```bash
mvn clean compile
```

## Rodar exemplos (simplified scripts)
```bash
# Consumer application
./run-consumer.sh

# Supplier application
./run-supplier.sh

# InvalidPayloadClient runner
./run-invalid-payload.sh
```

## Rodar com Maven (manual)
```bash
mvn package -DskipTests
java -cp example-consumer/target/anycall-example-consumer-0.0.1-SNAPSHOT.jar dev.kaiquebt.anycall.example.ConsumerApplication
java -cp example-supplier/target/anycall-example-supplier.jar dev.kaiquebt.anycall.example.SupplierApplication
java -cp example-consumer/target/anycall-example-consumer-0.0.1-SNAPSHOT.jar dev.kaiquebt.anycall.example.runners.InvalidPayloadClient
```
