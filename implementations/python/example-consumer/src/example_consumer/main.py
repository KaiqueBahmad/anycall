import logging
import os

from anycall import AnyCall

from .model.text_request import TextRequest

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(threadName)s] %(levelname)-5s %(name)s -- %(message)s"
)
logger = logging.getLogger(__name__)


def main() -> None:
    """Call a remote method and display the result."""
    redis_uri = os.getenv("REDIS_URI", "redis://localhost:6379")
    logger.info(f"Starting consumer with Redis URI: {redis_uri}")

    client = AnyCall.client(redis_uri, metrics_enabled=True)

    request = TextRequest(text="Hello, AnyCall!")
    logger.info(f"Calling analyze-sentiment with: {request.text}")

    response = client.call("analyze-sentiment", request)
    logger.info(f"Response: {response}")


if __name__ == "__main__":
    main()
