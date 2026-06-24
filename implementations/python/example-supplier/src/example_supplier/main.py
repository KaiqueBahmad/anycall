import logging
import os
import signal
import sys
import threading
from pathlib import Path

from anycall import AnyCall

from .sentiment_analyzer import SentimentAnalyzer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(threadName)s] %(levelname)-5s %(name)s -- %(message)s"
)
logger = logging.getLogger(__name__)


def write_health_file() -> None:
    """Write health check file."""
    try:
        xdg_runtime_dir = os.environ.get("XDG_RUNTIME_DIR")
        if xdg_runtime_dir:
            health_file = Path(xdg_runtime_dir) / "anycall" / "health"
        else:
            health_file = Path("/tmp/anycall/health")
        health_file.parent.mkdir(parents=True, exist_ok=True)
        health_file.write_text("OK")
        logger.info(f"Health file written to {health_file}")
    except Exception as e:
        logger.error(f"Failed to write health file: {e}")


def main() -> None:
    """Start the supplier server."""
    redis_uri = os.getenv("REDIS_URI", "redis://localhost:6379")
    logger.info(f"Starting supplier with Redis URI: {redis_uri}")

    server = AnyCall.server(redis_uri)
    server.register(SentimentAnalyzer())
    server.start()

    write_health_file()

    stop_event = threading.Event()

    def handle_signal(signum, frame):
        logger.info(f"Received signal {signum}, shutting down...")
        stop_event.set()

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    try:
        stop_event.wait()
    finally:
        server.stop()
        logger.info("Supplier stopped")


if __name__ == "__main__":
    main()
