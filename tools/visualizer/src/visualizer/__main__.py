import argparse
import os
import sys

from PyQt6.QtWidgets import QApplication

from .app import VisualizerApp


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Read-only dashboard for observing AnyCall traffic on Redis."
    )
    parser.add_argument(
        "--redis-uri",
        default=os.environ.get("ANYCALL_REDIS_URI", "redis://localhost:16379"),
        help="Redis connection URI (default: redis://localhost:16379, or $ANYCALL_REDIS_URI)",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=1.0,
        help="Poll interval in seconds (default: 1.0)",
    )
    args = parser.parse_args()

    app = QApplication(sys.argv)
    # Fusion fully respects our QSS stylesheet; native styles on Linux often
    # blend in system/GTK theme colors, which is what caused the low-contrast
    # dark-on-dark look before this was set explicitly.
    app.setStyle("Fusion")
    window = VisualizerApp(redis_uri=args.redis_uri, interval=args.interval)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
