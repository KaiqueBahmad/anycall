import argparse
import os
import subprocess
import sys

from PyQt6.QtWidgets import QApplication

from .app import VisualizerApp

# Probe run in a throwaway process: Qt aborts the process when a platform
# plugin fails to load, so "can xcb load here?" cannot be answered in-process.
_XCB_PROBE = (
    "import os; os.environ['QT_QPA_PLATFORM'] = 'xcb'; "
    "from PyQt6.QtGui import QGuiApplication; QGuiApplication([])"
)


def _prefer_xcb_backend() -> None:
    """Run on X11/XWayland when possible, so always-on-top actually works.

    Wayland gives clients no way to control stacking, so the always-on-top
    toggle is a no-op under a native Wayland backend -- on every compositor,
    not just one. XWayland ships with all the mainstream ones and does honour
    it, so a Wayland session gets the xcb backend when that backend can load
    (it needs the xcb-cursor library, which isn't always installed).
    """
    if os.environ.get("QT_QPA_PLATFORM"):
        return  # an explicit choice wins over ours
    if not os.environ.get("WAYLAND_DISPLAY"):
        return  # an X11 session already lands on xcb by itself
    if not os.environ.get("DISPLAY"):
        return  # no XWayland to fall back to
    try:
        probe = subprocess.run([sys.executable, "-c", _XCB_PROBE], capture_output=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return
    if probe.returncode == 0:
        os.environ["QT_QPA_PLATFORM"] = "xcb"


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

    _prefer_xcb_backend()
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
