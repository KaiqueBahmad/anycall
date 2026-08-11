import argparse
import os

from .app import VisualizerApp


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Read-only dashboard for observing AnyCall traffic on Redis."
    )
    parser.add_argument(
        "--redis-uri",
        default=os.environ.get("ANYCALL_REDIS_URI", "redis://localhost:6379"),
        help="Redis connection URI (default: redis://localhost:6379, or $ANYCALL_REDIS_URI)",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=1.0,
        help="Poll interval in seconds (default: 1.0)",
    )
    args = parser.parse_args()

    app = VisualizerApp(redis_uri=args.redis_uri, interval=args.interval)
    app.mainloop()


if __name__ == "__main__":
    main()
