FROM python:3.12-slim AS base
WORKDIR /app
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1
RUN mkdir -p /tmp/anycall

FROM base AS supplier
COPY . .
RUN uv sync --frozen --no-dev --package anycall-example-supplier
ENTRYPOINT ["uv", "run", "--no-sync", "python", "-m", "example_supplier.main"]

FROM base AS consumer
COPY . .
RUN uv sync --frozen --no-dev --package anycall-example-consumer
ENTRYPOINT ["uv", "run", "--no-sync", "python", "-m", "example_consumer.main"]
