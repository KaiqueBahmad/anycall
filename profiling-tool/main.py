import sys
from PySide6.QtWidgets import QApplication
from app.main_window import MainWindow
from app.theme import APP_STYLE


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(APP_STYLE)

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
