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
```

## Rodar com Maven (manual)

Os exemplos rodam via `exec-maven-plugin`, ligado à fase `compile`. O comando
abaixo compila o módulo (e suas dependências, via `-am`) e executa a `mainClass`
configurada:

```bash
# Consumer (ConsumerApplication)
mvn compile -pl example-consumer -am -DskipTests -q

# Supplier (SupplierApplication)
mvn compile -pl example-supplier -am -DskipTests -q
```

> A classe `dev.kaiquebt.anycall.example.runners.InvalidPayloadClient` existe no
> módulo `example-consumer` para testes de payload inválido, mas a `mainClass`
> executada pelo `exec-maven-plugin` é fixa (`ConsumerApplication`). Para rodá-la,
> ajuste a `mainClass` no `example-consumer/pom.xml`.
