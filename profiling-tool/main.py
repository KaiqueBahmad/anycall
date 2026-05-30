import sys
import logging
import threading

from PySide6.QtWidgets import QApplication
from app.main_window import MainWindow
from app.theme import APP_STYLE

# Setup logging to see all errors
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)

# Capture thread exceptions
def thread_exception_hook(args):
    logger.error(f"Thread exception: {args.exc_type.__name__}: {args.exc_value}")
    logger.error(f"Thread: {args.thread}")

threading.excepthook = thread_exception_hook


def main():
    try:
        logger.info("Starting application")
        app = QApplication(sys.argv)
        app.setStyle("Fusion")
        app.setStyleSheet(APP_STYLE)

        logger.info("Creating MainWindow")
        window = MainWindow()
        window.show()

        logger.info("Entering event loop")
        sys.exit(app.exec())
    except Exception as e:
        logger.error(f"Fatal error: {str(e)}", exc_info=True)
        raise


if __name__ == "__main__":
    main()
