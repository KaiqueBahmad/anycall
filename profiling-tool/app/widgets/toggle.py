from PySide6.QtWidgets import QAbstractButton
from PySide6.QtCore import QPropertyAnimation, QEasingCurve, Property, QRectF, Qt
from PySide6.QtGui import QPainter, QColor

from app.theme import ACCENT_ON, ACCENT_OFF, TEXT


class ToggleSwitch(QAbstractButton):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setFixedSize(40, 22)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._t = 0.0
        self._anim = QPropertyAnimation(self, b"t", self)
        self._anim.setDuration(200)
        self._anim.setEasingCurve(QEasingCurve.Type.InOutQuad)
        self.toggled.connect(self._on_toggle)

    def _on_toggle(self, checked: bool):
        self._anim.stop()
        self._anim.setStartValue(self._t)
        self._anim.setEndValue(1.0 if checked else 0.0)
        self._anim.start()

    def get_t(self):
        return self._t

    def set_t(self, v: float):
        self._t = v
        self.update()

    t = Property(float, get_t, set_t)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        w, h = self.width(), self.height()
        radius = h / 2

        off = QColor(ACCENT_OFF)
        on  = QColor(ACCENT_ON)
        track = QColor(
            int(off.red()   + self._t * (on.red()   - off.red())),
            int(off.green() + self._t * (on.green() - off.green())),
            int(off.blue()  + self._t * (on.blue()  - off.blue())),
        )

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(track)
        p.drawRoundedRect(0, 0, w, h, int(radius), int(radius))

        margin = 2
        size = h - 2 * margin
        x = margin + self._t * (w - h)
        p.setBrush(QColor(TEXT))
        p.drawRoundedRect(int(x), margin, int(size), int(size), 2, 2)
