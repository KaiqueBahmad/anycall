import logging
import os
import statistics
import time

from anycall import AnyCall

from .model.text_request import TextRequest

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(threadName)s] %(levelname)-5s %(name)s -- %(message)s"
)
logger = logging.getLogger(__name__)


def main() -> None:
    """Run consumer load test."""
    redis_uri = os.getenv("REDIS_URI", "redis://localhost:6379")
    logger.info(f"Starting consumer with Redis URI: {redis_uri}")

    client = AnyCall.client(redis_uri, metrics_enabled=True)

    logger.info("Running warmup call...")
    warmup_response = client.call(
        "analyze-sentiment",
        TextRequest(text="warmup")
    )
    logger.info(f"Warmup response: {warmup_response}")

    total = 100
    timings = []

    logger.info(f"Running {total} load test calls...")
    for i in range(1, total + 1):
        start_ns = time.time_ns()
        response = client.call(
            "analyze-sentiment",
            TextRequest(text=f"test-{i}")
        )
        elapsed_ms = (time.time_ns() - start_ns) / 1_000_000
        timings.append(elapsed_ms)

        if i % 20 == 0:
            logger.info(f"Completed {i}/{total} calls")

    logger.info("Load test complete. Statistics:")
    min_ms = min(timings)
    max_ms = max(timings)
    avg_ms = statistics.mean(timings)
    median_ms = statistics.median(timings)
    p95_ms = statistics.quantiles(timings, n=20)[18] if len(timings) > 1 else timings[0]
    p99_ms = statistics.quantiles(timings, n=100)[98] if len(timings) > 1 else timings[0]

    print()
    print("----------------------------------------")
    print(f"Min:    {min_ms:8.2f} ms")
    print(f"Avg:    {avg_ms:8.2f} ms")
    print(f"p50:    {median_ms:8.2f} ms")
    print(f"p95:    {p95_ms:8.2f} ms")
    print(f"p99:    {p99_ms:8.2f} ms")
    print(f"Max:    {max_ms:8.2f} ms")
    print("----------------------------------------")


if __name__ == "__main__":
    main()
